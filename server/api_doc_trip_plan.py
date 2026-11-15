from copy import deepcopy

from api_doc_shared import entry, response, READ, BROWSER, IDENT, ACCOUNT, arr, b, s, n, nullable
from api_doc_trips import (strict, result, status, DETAIL, CAR_PLACES, CAR_PLACE_FIELDS, ROUTE_ITEMS,
    OPS as TRIP_OPS, BODY as TRIP_BODY, ROUTE_PLAN)
from api_doc_trip_merge import OPS as MERGE_OPS, BODY as MERGE_BODY

T = '/v1/social/trips/{id}'
C = T + '/cars/{carId}'
N = '/v1/native/trips/{id}'
BODY = {
    ('post', C + '/places'): strict(CAR_PLACE_FIELDS, '이 차의 운전자 또는 탑승자. kind별 최대 10개.'),
    ('put', C + '/route-order'): dict(strict({'items': ROUTE_ITEMS,
        'routeRevision': n('직전 상세의 차 경로 변경 번호. 생략은 기존 번호가 0인 경로에서만 허용.', minimum=0, maximum=2147483647)},
        '운전자만 순서 저장. 현재 routeRevision 불일치는 409 Route revision conflict. 생략한 픽업·드랍의 위치와 선택은 보존.'), required=['items']),
    ('put', C + '/route-progress'): strict({'next': nullable(dict(ROUTE_ITEMS['items'],
        description='운전자 차량이 지금 안내받아 향하는 장소 항목. 도착을 확인한 장소는 지정할 수 없음. null이면 경로 끝.')),
        'routeRevision': n('직전 상세에서 확인한 내 차 경로 변경 번호.', minimum=0, maximum=2147483647)},
        '진행 중인 여행의 해당 차 운전자만 지금 안내받는 장소를 보고합니다. null은 경로 끝. routeRevision 충돌은 409 Route revision conflict, 이미 도착 확인한 장소나 도착 확인이 남았는데 null이면 409 TRIP_ROUTE_PROGRESS_CHANGED이며 여행 revision을 갱신하지 않습니다.'),
    ('post', C + '/ride-invites'): strict({'accountId': ACCOUNT}, '수락 멤버 중 운전자가 아닌 대상.'),
    ('post', C + '/ride-invites/{inviteId}/respond'): strict({'accept': b('수락 시 다른 차에서 이동.')}, '대상 본인만 응답.')
}
NO_BODY = set()
BODY[('put', C + '/route-order')]['properties']['routeContractVersion'] = n('2면 픽업·공유·드랍 순서와 공유 코스 순서를 검사. 생략 시 기존 계약.', minimum=2, maximum=2)
BODY[('post', C + '/route-arrivals')] = strict({'routeRevision': n('현재 차 경로 번호.', minimum=0, maximum=2147483647),
    'progressRevision': n('현재 v2 진행 번호.', minimum=0, maximum=2147483647), 'item': dict(ROUTE_ITEMS['items'], description='현재 서버 routePlan.next와 일치하는 도착 항목.')},
    '운전자만 v2 다음 장소 도착을 명시 보고. 물리적 위치 검증을 의미하지 않음. 추가 키 거절.')
BODY['post', C + '/route-arrivals']['properties']['singleJoinCompletion'] = s('새 차량 앱이 한 장소 첫 공유 코스의 합류 시 선택. 생략은 기존 v2 완료 의미 유지. 처리한 합류의 선택은 재전송으로 바꾸지 않습니다.', enum=['explicit-v1'])
OPS = {}
for method, suffix, summary, effects, schema, code in [
    ('get', '/places', '차별 장소 조회', 'v1은 운전자·탑승자·방장에게 상세 필드, 다른 멤버는 이름과 선택자 수. v2는 현재 운전자·동승자만 개인 장소를 받고 다른 차는 방장이어도 빈 배열. 차단 상대 숨김.', strict({'places': CAR_PLACES}, '차별 장소.'), '200'),
    ('post', '/places', '차별 장소 추가', '운전자 또는 탑승자. 403 Only the driver or a passenger may add a place. 409 Car place limit reached. 이름·좌표는 암호화 저장하고 운전자 포함 여행 멤버에게 기존 알림.', strict({'id': IDENT}, '장소 ID.'), '201'),
    ('delete', '/places/{placeId}', '차별 장소 삭제', '운전자 또는 추가한 본인. 403 Only the driver or author may delete the place. 선택과 순서 참조 정리.', status('deleted'), '200'),
    ('put', '/places/{placeId}/select', '픽업·드랍 선택', '탑승자 본인만 kind별 기존 선택 교체. 403 Only a passenger may select a place.', status('selected'), '200'),
    ('delete', '/places/{placeId}/select', '픽업·드랍 선택 해제', '이 위치에 대한 내 선택만 해제. 탑승자만.', status('unselected'), '200'),
    ('put', '/route-order', '차 경로 순서 저장', '운전자만. routeRevision 불일치는 409 Route revision conflict이며 번호 생략은 기존 번호가 0일 때만 허용합니다. 코스 누락은 400 All course places are required. 잘못된 참조·중복은 400 Invalid route order. v1 동일 좌표 드랍은 course.dropRef로 합칩니다. routeContractVersion=2면 준비 중 픽업·공유·드랍 구간과 정본 공유 순서만 허용하고 드랍은 별도 마지막 구간입니다. v2 출발 이후 수정은 409 TRIP_ROUTE_PLAN_LOCKED.', status('updated'), '200'),
    ('put', '/route-progress', '차 경로의 다음 장소 보고', '진행 중 여행의 운전자만 현재 routeRevision과 일치하는 안내 대상 장소 또는 null을 암호화 저장하고 같은 차 탑승자 상세의 routeNext로 보여 줍니다. 불일치는 409 Route revision conflict. 도착 확인은 route-arrivals로만 하며, 이미 도착 확인한 장소를 지정하거나 남은 도착이 있는데 null이면 409 TRIP_ROUTE_PROGRESS_CHANGED. 진행 중이 아니면 409 TRIP_STATE_CONFLICT, 차 경로에 없는 항목은 400 Next place is not in the car route. 도착 진행(routePlan)과 phase는 바꾸지 않고 여행 revision도 갱신하지 않으며 route 이벤트만 알립니다.', status('updated'), '200'),
    ('post', '/route-arrivals', '구간 경로 장소 도착 보고', '명시적 v2 여행의 현재 운전자만. 다음 항목 도착만 허용(409 TRIP_ROUTE_PROGRESS_CHANGED). 모든 차 합류 후 공유 시작, 모든 차 드랍 완료 후 기존 종료·권한 철회·결과 저장. 같은 도착의 재시도는 종료 뒤에도 200 unchanged. 손들기는 active 여행의 픽업·대기·공유·드랍에서 허용. 해당 차 done이면 TRIP_SIGNAL_ROUTE_FINISHED.', strict({'status': s('저장 결과.', enum=['updated', 'unchanged']), 'routePlan': nullable(ROUTE_PLAN)}, '현재 차의 권한 필터링된 진행 상태.'), '200'),
    ('post', '/ride-invites', '태우기 요청', '운전자만. 대상은 accepted 비운전자, 404 Account unavailable / 409 Already driving / 409 Car is full. 중복은 같은 ID를 201로 반환.', strict({'id': IDENT}, '요청 ID.'), '201'),
    ('post', '/ride-invites/{inviteId}/respond', '태우기 요청 응답', '대상 본인. 수락은 기존 ride와 같은 이동·선택·리모컨 요청 정리. 좌석 재검사 409 Car is full, 실패하면 요청과 이전 좌석 보존.', status('accepted', 'declined'), '200'),
    ('delete', '/ride-invites/{inviteId}', '태우기 요청 취소', '운전자만. 404 Ride invite unavailable.', status('cancelled'), '200'),
    ('delete', '/riders/{accountId}', '탑승자 내리기', '운전자만. 404 Passenger unavailable. 좌석·선택·대기 리모컨 정리 후 unassigned.', status('removed'), '200'),
    ('post', '/courses/{packId}/complete', '차별 코스 완료', '현재 운전자만. v1은 active에서만(409 TRIP_STATE_CONFLICT). v2는 해당 코스의 모든 도착과 전체 합류가 저장된 뒤 완료·최종 결과 첨부를 확인하며, 자동 완료된 completed 여행에서도 같은 완료 코스의 최종 첨부·동일 재시도를 허용합니다. 도착 전은 409 TRIP_ROUTE_PROGRESS_CHANGED. 404 Course unavailable. 중복 200은 revision·알림을 다시 올리지 않습니다.', status('completed'), '200'),
]:
    path = C + suffix
    OPS[method, path] = entry('여행', summary, READ if method == 'get' else BROWSER,
        '여행 상세의 현재 차·멤버·장소 ID 사용.', effects,
        '웹 쓰기는 CSRF, 정확한 JSON 키·4096바이트 상한. 현재 상태로 재조회. 알림은 기존 friends/devices invalidate.',
        result(schema, code), ['400', '401', '403', '404', '409', '413', '429', '503'])
    if method != 'get' and (method, path) not in BODY:
        NO_BODY.add((method, path))

NATIVE = {('get', N), ('get', N + '/friends')}
ALIASES = [('get', C + '/places'), ('put', C + '/route-order'), ('put', C + '/route-progress'), ('post', C + '/route-arrivals'), ('post', C + '/courses/{packId}/complete'),
    ('get', T + '/location-sharing'), ('patch', T + '/location-sharing'),
    ('post', T + '/start'), ('post', T + '/finish'), ('patch', T), ('post', T + '/members'),
    ('delete', T + '/members/{accountId}'), ('post', T + '/link'), ('delete', T + '/link'),
    ('post', T + '/cars'), ('patch', C), ('delete', C), ('put', C + '/ride'), ('delete', T + '/ride'),
    ('post', T + '/courses'), ('delete', T + '/courses/{packId}'),
    ('post', C + '/places'), ('delete', C + '/places/{placeId}'),
    ('post', C + '/ride-invites'), ('delete', C + '/ride-invites/{inviteId}'), ('delete', C + '/riders/{accountId}')]
all_ops, all_body = {**TRIP_OPS, **MERGE_OPS, **OPS}, {**TRIP_BODY, **MERGE_BODY, **BODY}
for method, original in ALIASES:
    path = original.replace('/social/', '/native/')
    key = (method, path)
    NATIVE.add(key)
    OPS[key] = deepcopy(all_ops[method, original])
    OPS[key]['prerequisites'] = '현재 Native mTLS·Bearer와 rooms:read(조회) 또는 rooms:interact(쓰기). 웹과 같은 업무 권한.'
    if original == C + '/route-progress':
        OPS[key]['prerequisites'] = '현재 Native mTLS·Bearer와 rooms:read·rooms:interact 모두 필요. 진행 중인 여행의 해당 차 운전자만 보고.'
    OPS[key]['retry'] = '쓰기 JSON에 현재 functionalRevision 필수. 상태 전환에는 별도 여행 revision도 필수. 트랜잭션 안에서 모두 재검사.'
    if method != 'get':
        source = all_body.get((method, original))
        BODY[key] = deepcopy(source) if source and source.get('properties') else strict({}, 'functionalRevision 외 업무 필드 없음.')

OPS['get', N] = deepcopy(TRIP_OPS['get', T])
OPS['get', N]['effects'] += ' native 상세 link는 owner/invite 권한자에게 active·expiresAt만 반환하고 나머지는 null. 날짜·state·revision·places·routeOrder·stops·completedCarIds·rideInvites는 같은 가시성 규칙.'
FRIEND = strict({'id': ACCOUNT, 'name': s('친구 표시 이름.'), 'hasVehicle': b('live 번호판 보유 기기 분류.'),
    'tripState': s('이 여행의 참여 상태.', enum=['none', 'pending', 'accepted'])}, '번호판·이메일·기기 ID 없는 친구.')
OPS['get', N + '/friends'] = entry('여행', '여행 초대용 친구 목록', 'Native rooms:read와 여행 owner/invite 권한.',
    '초대 화면에서 조회 후 members POST로 선택한 친구 초대.', 'overview와 같은 수락 비차단 친구 분류. 여행 소유자 차단 상대는 제외.',
    '현재 권한으로 다시 조회. 기기 요청 형식이 맞지 않으면 400, 방장·invite 권한이 없으면 403, 비멤버·pending은 404 Trip unavailable.',
    result(strict({'friends': arr(FRIEND, '계정 ID 순서의 친구.')}, '여행 초대용 친구 목록.')), ['400', '401', '403', '404', '503'])

from api_doc_shared import n, nullable, TIME
DISPLAY_EVENT = strict({'id': s('도착/코스 완료 기록 ID.'), 'name': s('현재 볼 수 있는 장소 또는 코스 이름.'),
    'kind': s('방문 기록 또는 코스 완료.'), 'at': TIME}, '실제로 저장된 본인 기록/내 차 완료 시각. 경유지 추가만으로 도착을 만들지 않습니다.')
DISPLAY_MUSIC = strict({'name': nullable(s('선택 목록 이름.')), 'currentTitle': nullable(s('선택 곡 제목.')),
    'trackCount': n('현재 선택 목록 또는 공유 목록의 실제 곡 수.', minimum=0),
    'djName': nullable(s('현재 곡 추가자 또는 선택자 이름.'))}, '기능 목적과 여행 음악 받기 동의가 유효할 때만 반환. 빈 목록은 trackCount=0.')
DISPLAY_COMPANION = dict(type='object', additionalProperties=False, properties={
    'carId': IDENT, 'label': s('공유가 꺼짐/최근 공유 위치 없음 등의 실제 상태.'),
    'distanceMeters': dict(type='number', minimum=0, description='내 차 경로에 투영한 대략적인 앞/뒤 거리.'),
    'direction': s('내 차 기준.', enum=['ahead', 'behind'])}, required=['carId'])
DISPLAY = strict({'serverNow': TIME, 'validUntil': TIME, 'endedAt': nullable(TIME),
    'timeline': arr(DISPLAY_EVENT, '본인 저장 방문 기록과 내 차 코스 완료 기록.'),
    'visitCount': nullable(n('현재 본인 방문 기록 수. 조회할 기록이 없으면 null.', minimum=0)),
    'metrics': dict(type='null', description='원시 주행 데이터 수집과 분석을 폐지하여 항상 null.'),
    'music': nullable(DISPLAY_MUSIC), 'companions': arr(DISPLAY_COMPANION, '원시 좌표를 포함하지 않는 공유 상태/상대 거리.')},
    '같은 native 여행 상세의 읽기 표시용 투영. 짧은 유효기간과 기존 도메인 동의를 재검사하며 점수/순위는 제공하지 않습니다.')
OPS['get', N]['responses']['200']['content']['application/json']['schema']['properties']['display'] = DISPLAY
OPS['get', N]['effects'] += ' display는 현재 history:read/room-music:read/vehicle-reports:read 및 각 도메인 동의로 필터링합니다. Android는 validUntil 이후 숨깁니다.'

from api_doc_trips import DRIVING_SCORE
SCORE_VALUE = deepcopy(DRIVING_SCORE)
SCORE_VALUE['properties'].pop('carId')
SCORE_VALUE['required'].remove('carId')
SCORE_PATH = N + '/cars/{carId}/courses/{packId}/driving-score'
NATIVE.add(('put', SCORE_PATH))
BODY['put', SCORE_PATH] = strict({'drivingScore': SCORE_VALUE},
    'final=false만 허용. functionalRevision 필수. 정확한 다섯 키만 받으며 원시 속도·시각 표본 등 추가 키 거절.')
OPS['put', SCORE_PATH] = entry('여행', '같은 차에 코스 안전운전 점수 공유',
    '현재 native 운전자 기기·rooms:interact·같은 여행 참여 자격 필요. 별도 점수 동의 불필요.',
    '점수 변화 때만 현재 코스의 점수와 사건 횟수를 전송.',
    'active 여행의 현재 차 운전자만 차·코스·버전별 최신 한 건 암호화 저장. v2는 전체 합류 뒤 shared 단계의 현재 공유 코스만 허용하며 그 밖은 409 DRIVING_SCORE_PHASE_CONFLICT. 합의 경유지 중에는 진행 중 코스 평가를 유지합니다. 같은 차 탑승자만 상세 drivingScores로 조회. 원시 속도·표본 거절.',
    '동일 값은 unchanged, 변경은 updated. 이미 완료한 코스의 진행 중 보고, 확정 결과 변경 또는 줄어든 횟수는 409 DRIVING_SCORE_CONFLICT. 새 기능 동의를 기존 승인에 자동 추가하지 않습니다.',
    result(status('updated', 'unchanged')), ['400', '401', '403', '404', '409', '413', '429', '503'])
SCORE_COMPLETE = N + '/cars/{carId}/courses/{packId}/complete'
BODY['post', SCORE_COMPLETE] = dict(strict({'drivingScore': SCORE_VALUE},
    '선택 객체가 있으면 final=true와 현재 운전자 기기·여행 자격 확인 필요. 별도 점수 동의 없음. 생략한 기존 완료 요청은 유지.'), required=[])
OPS['post', SCORE_COMPLETE]['effects'] += ' 선택 drivingScore는 같은 트랜잭션에서 확정·저장하며 원시 표본을 받지 않습니다. 추가 공유 동의 없는 점수 첨부는 403.'

COMPLETE_PROGRESS = {
    'routeRevision': n('단일 합류 장소 코스의 명시 완료에 필요한 현재 차 경로 번호. progressRevision과 함께 보냅니다.', minimum=0, maximum=2147483647),
    'progressRevision': n('단일 합류 장소 코스의 명시 완료에 필요한 현재 진행 번호. routeRevision과 함께 보냅니다.', minimum=0, maximum=2147483647)}
for complete_path in (C + '/courses/{packId}/complete', SCORE_COMPLETE):
    NO_BODY.discard(('post', complete_path))
    BODY.setdefault(('post', complete_path), dict(strict({}, '코스 완료.'), required=[]))
    BODY['post', complete_path]['properties'].update(deepcopy(COMPLETE_PROGRESS))
    OPS['post', complete_path]['effects'] += ' 첫 코스가 합류 장소 한 곳이고 최초 합류에서 singleJoinCompletion=explicit-v1을 선택한 차만 shared 시작을 별도 기록합니다. 옵션 없는 기존 도착 의미는 유지합니다. 실제 코스 완료는 이 요청에 routeRevision과 progressRevision을 함께 보내야 합니다. 한 필드만 보내거나 잘못된 정수는 400 TRIP_ROUTE_PROGRESS_INVALID, 이전 진행·미완료 합의 경유지는 409 TRIP_ROUTE_PROGRESS_CHANGED. 이미 마친 코스의 기존 본문과 재전송은 유지합니다.'

TOTAL_SCORE_PATH = N + '/cars/{carId}/driving-score'
NATIVE.add(('put', TOTAL_SCORE_PATH))
BODY['put', TOTAL_SCORE_PATH] = strict({'drivingScore': SCORE_VALUE}, '여행 전체 누적 점수. active 전 구간; final은 경로 done 또는 여행 completed. functionalRevision 필수.')
OPS['put', TOTAL_SCORE_PATH] = entry('여행', '여행 전체 안전운전 점수 보고',
    '현재 native 운전자 기기(같은 계정의 mTLS·Bearer)와 rooms:interact, 이 기기의 유효한 차량 연결, 같은 여행 참여 자격이 필요합니다. 별도 점수 동의는 없습니다.',
    'functionalRevision과 drivingScore의 다섯 필드(score·accelerations·brakings·measurable·final)를 전송합니다. 원시 속도·위치·시각 표본은 거절합니다.',
    '구간 경로 계약(v2)으로 시작한 여행의 해당 차 운전자만 차별 최신 보고 한 건을 암호화 대결 레코드에 저장하고 route 영역을 알립니다. '
    '진행 중에는 active 전 구간에서 보고하고, final은 해당 차 경로 done 또는 여행 completed 때만 허용합니다. completed 뒤에는 final만 받습니다.',
    '같은 값·같은 보고 기기는 unchanged. 400 Invalid driving score fields 등 형식 오류, 403 Native driver device required(차량 기기 아님) / DRIVING_SCORE_DEVICE_REQUIRED(현재 차량 연결 없음), '
    '404 Driving score unavailable(운전자 아님·대결 제외 차), 409 TRIP_ROUTE_CONTRACT_REQUIRED(v2 아님) / TRIP_STATE_CONFLICT(active·completed 아님, completed 뒤 진행 중 보고) / '
    'DRIVING_SCORE_PHASE_CONFLICT(경로 done 전 final) / DRIVING_SCORE_CONFLICT(확정값 변경·횟수 감소·측정 가능에서 불가로 변경).',
    result(status('updated', 'unchanged')), ['400', '401', '403', '404', '409', '413', '429', '503'])
