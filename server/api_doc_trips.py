"""기존 여행 조회·초대 계약. 통합 상세와 활동은 api_doc_trip_merge에서 별도로 정의한다."""
from api_doc_shared import entry, response, obj, s, n, b, arr, nullable, IDENT, ACCOUNT, TIME, READ, BROWSER
from api_doc_friend_remotes import REMOTE_POLICY, REMOTE_POLICY_INPUT, REMOTE_POLICY_RESULT


def strict(fields, description):
    return dict(obj(fields, description), additionalProperties=False)


REMOTE_ACTION = strict({'id': s('현재 remoteOptions에서 선택한 조작 ID.'),
    'revision': n('선택한 조작의 정확한 계약 버전.', minimum=1)}, '서버 옵션의 ID와 버전 쌍.')
REMOTE_OPTION = strict(dict(REMOTE_ACTION['properties'], label=s('서버가 제공하는 조작 표시 이름.'),
    argumentKind=s('서버가 제공하는 인자 종류.')), 'FriendVehicleControls.options()의 현재 조작 옵션.')
REMOTE_DISPLAY_ACTION = strict(dict(REMOTE_ACTION['properties'], label=s('서버가 제공하는 조작 표시 이름.')),
    '현재 옵션과 일치하는 요청 또는 명시 허용 조작.')
REMOTE = strict({'status': s('현재 차주의 기기에 대한 내 명시 허용 상태.', enum=['none', 'granted']),
    'requestId': nullable(IDENT), 'actions': arr(REMOTE_DISPLAY_ACTION,
        '현재 차 정책이 허용한 조작만, 그 외에는 빈 배열.')},
    '선택한 여행 차의 현재 사전 허용 상태. requestId는 항상 null이며 차량 제어는 진행 중에만 가능합니다.')
REMOTE_REQUEST = strict({'id': IDENT, 'carId': IDENT, 'requesterId': ACCOUNT, 'requesterName': s('요청자의 현재 표시 이름.'),
    'createdAt': TIME, 'actions': arr(REMOTE_DISPLAY_ACTION, '요청 항목 중 현재 remoteOptions와 일치하는 항목. 나머지는 제외합니다.')},
    '이 차에서 나를 차주로 지정한 대기 요청. vehicle 멤버에게만 표시합니다.')
PACK = s('작성한 기존 코스의 안정 pack ID.', pattern='^[a-z0-9][a-z0-9_-]{0,79}$', maxLength=80)
COURSE = strict({'packId': PACK, 'version': n('v1은 조회 시점의 최신 공개 버전, v2는 출발할 때 고정한 게시 버전.', minimum=1),
    'title': s('응답 버전의 코스 제목. 코스는 추가 즉시 일행에게 표시하며 사후 공개 제한은 유지합니다.'),
    'stopCount': n('공개 코스와 이 여행의 추가 경유지를 포함한 장소 수.', minimum=1, maximum=6),
    'addedById': ACCOUNT, 'addedByName': s('코스를 추가한 계정의 현재 표시 이름.'),
    'mine': b('내가 추가한 코스 여부.'), 'canRemove': b('추가한 본인 또는 edit 권한으로 제거할 수 있는지.'),
    'reviewed': b('하위 호환 가용성 필드. 반환되는 코스는 true이며 사전 승인 절차가 없습니다.')}, 'v1은 첨부 순서의 최신 코스, v2는 출발 때 고정한 공유 순서·버전. 현재 차단·신고·삭제 공개 제한을 유지합니다.')
TITLE = s('양끝 공백 제거 후 1~40자. 제어문자 금지.', minLength=1, maxLength=40)
DESCRIPTION = s('양끝 공백 제거 후 0~300자. 줄바꿈 외 제어문자 금지.', maxLength=300)
PERMISSIONS = strict({'invite': b('친구 초대·여행 링크 관리.'), 'edit': b('제목·설명·코스 관리.')}, '방장은 항상 두 권한을 갖습니다.')
PERSON = strict({'id': ACCOUNT, 'name': s('현재 표시 이름.')}, '차단 상대를 제외한 사람.')
MEMBER = strict(dict(PERSON['properties'], state=s('참여 상태.', enum=['pending', 'accepted']),
    via=s('참여 경로.', enum=['friend', 'link']), isOwner=b('방장.'), isMe=b('본인.'), isFriend=b('현재 친구.'),
    friendRequest=s('나 기준 요청 방향.', enum=['none', 'sent', 'received']), hasVehicle=b('번호판이 있는 live 기기 보유.'),
    carId=nullable(IDENT), readiness=s('출발 준비 상태. invited=수락 전, needsCar=탈 차 미정, needsVehicle=운전자인데 차량 미연결, needsPlaces=동승자인데 픽업·드랍 미선택, ready=준비 완료. 차단으로 가려진 차도 실제 배정 기준으로 판정합니다.', enum=['invited', 'needsCar', 'needsVehicle', 'needsPlaces', 'ready']), role=s('현재 표시 역할. 권한을 추가하지 않습니다.', enum=['member', 'dj', 'food', 'rest']), permissions=nullable(PERMISSIONS)), '방장 우선. pending은 방장·invite 보유자에게만, permissions는 방장에게만 표시.')
PASSENGER = strict(dict(PERSON['properties'], isMe=b('본인.'),
    remoteGranted=b('이 동승자에게 준 여행 리모컨 허용 여부. 이 차의 운전자만 받습니다.')), '이 차의 동승자.')
PASSENGER['required'] = [*PERSON['properties'], 'isMe']
CAR_FIELDS = {'name': s('차 이름 1~20자, 공백 제거, 제어문자 금지.', minLength=1, maxLength=20),
    'seats': n('운전자를 제외한 좌석 수.', minimum=1, maximum=8)}
CAR = strict(dict(CAR_FIELDS, id=IDENT, driverId=ACCOUNT, driverName=s('운전자 표시 이름.'),
    ordinal=n('여행 안에서 생성 시 부여한 안정 차량 순번. 삭제·차단 뒤 다른 차의 번호를 당기거나 재사용하지 않습니다.', minimum=1, maximum=2147483647),
    isMine=b('내가 운전자.'), iRide=b('내가 동승.'), driverVehicleReady=b('현재 차량 분류가 vehicle.'),
    passengers=arr(PASSENGER, '보이는 동승자.'), remote=nullable(REMOTE), remotePolicy=nullable(REMOTE_POLICY)), '내가 동승한 차에만 remote를 제공합니다.')
LINK_STATE = strict({'active': b('만료되지 않은 링크 존재.'), 'expiresAt': nullable(TIME)}, '웹·차량의 owner/invite 권한자에게만 active·expiresAt을 표시합니다. 상세는 토큰·초대 링크를 반환하지 않으며 권한이 없으면 null입니다.')
TOKEN = s('secrets.token_urlsafe(32) 토큰. 공유 URL fragment와 JSON 본문으로만 전달하며 서버에는 SHA-256만 저장합니다.', pattern='^[A-Za-z0-9_-]{43}$')
LINK = strict({'token': TOKEN, 'expiresAt': TIME}, '7일 만료. 재발급은 이전 링크를 교체합니다.')
SUMMARY = strict({'id': IDENT, 'title': TITLE, 'isOwner': b('방장.'), 'ownerName': s('방장 이름.'),
    'memberCount': n('내게 보이는 수락 인원.', minimum=1, maximum=20), 'carCount': n('내게 보이는 차 수.', minimum=0, maximum=20),
    'routePreview': dict(arr(strict(dict(name=s('현재 공유 코스 장소 이름.'), courseId=PACK, ref=PACK),
        '픽업·드랍을 제외한 현재 보이는 공유 코스 장소.'), '목록 경로선용 장소. 도착 상태를 추정하지 않습니다.'), maxItems=4)}, '내 수락 여행.')
INVITATION = strict({'tripId': IDENT, 'title': TITLE, 'ownerName': s('방장 이름.')}, '내 pending 초대.')
PAGE = strict({'trips': arr(SUMMARY, '내 여행.'), 'invitations': arr(INVITATION, '내 초대.')}, '목록.')
DRIVING_SCORE = strict({'carId': IDENT,
    'score': nullable(n('측정 가능한 경우 max(0,100-5*(급가속+급감속))와 같은 점수.', minimum=0, maximum=100)),
    'accelerations': n('급가속 사건 수.', minimum=0, maximum=2147483647),
    'brakings': n('급감속 사건 수.', minimum=0, maximum=2147483647),
    'measurable': b('속도 신호로 측정한 결과인지. false면 score는 null.'),
    'final': b('코스 완료 시 확정한 결과인지.')}, '현재 요청자가 탄 차의 코스별 점수와 사건 횟수. 원시 속도·표본은 없음.')
COURSE['properties']['drivingScores'] = dict(arr(DRIVING_SCORE, '같은 차 최신 점수 한 건, 없거나 미탑승이면 빈 목록.'), maxItems=1)
COURSE['required'].append('drivingScores')
DETAIL = strict({'id': IDENT, 'title': TITLE, 'description': DESCRIPTION, 'isOwner': b('방장.'), 'ownerId': ACCOUNT,
    'myPermissions': PERMISSIONS, 'members': arr(MEMBER, '여행 멤버.'), 'link': nullable(LINK_STATE),
    'cars': arr(CAR, '여행 차.'), 'unassigned': arr(PERSON, '운전·동승하지 않은 수락 멤버.'),
    'remoteOptions': arr(REMOTE_OPTION, '서버의 현재 옵션.'), 'remoteRequests': dict(arr(REMOTE_REQUEST, '구형 클라이언트용 호환 필드. 사전 허용에서는 항상 빈 배열.'), maxItems=0),
    'courses': dict(arr(COURSE, 'v1 최신 첨부 코스 또는 v2 출발 때 고정한 공유 코스.'), maxItems=10)}, '수락 멤버만 읽는 여행 상세.')
PREVIEW = strict({'tripId': IDENT, 'title': TITLE, 'description': DESCRIPTION, 'ownerName': s('방장 이름.'),
    'memberCount': n('차단 제외 수락 인원.', minimum=0, maximum=20), 'expiresAt': TIME, 'alreadyMember': b('이미 수락 멤버.')}, '여행 링크 미리보기.')
FRIEND_PREVIEW = strict({'ownerName': s('링크 소유자 이름.'), 'expiresAt': TIME, 'alreadyFriends': b('현재 친구.')}, '친구 링크 미리보기.')
DATE = nullable(s('YYYY-MM-DD 여행 날짜. 두 날짜가 있으면 0~30일 간격.', format='date', pattern=r'^\d{4}-\d{2}-\d{2}$'))
DATES = {'startDate': DATE, 'endDate': DATE}
LOCATION_CONSENT = b('이번 여행의 현재 일행에게 내 위치를 공유할지 나타냅니다. 링크로 참여한 비친구도 포함되며 차단 관계를 적용합니다.')
TRIP_STATE = s('여행 생명주기 상태.', enum=['planned', 'active', 'completed', 'cancelled'])
STOP = strict({'id': PACK, 'name': s('코스 장소 이름.'), 'lat': dict(type='number', minimum=-90, maximum=90, description='유한 위도 -90~90.'),
    'lng': dict(type='number', minimum=-180, maximum=180, description='유한 경도 -180~180.')}, '응답 코스 버전의 장소. v2는 출발 때 고정한 장소. 코스는 사전 승인 없이 일행에게 같은 장소를 반환합니다.')
CAR_PLACE_FIELDS = {'kind': s('픽업 또는 드랍.', enum=['pickup', 'drop']),
    'name': s('공백 제거 후 1~40자, 제어문자 금지.', minLength=1, maxLength=40),
    'lat': dict(type='number', minimum=-90, maximum=90, description='유한 위도 -90~90.'), 'lng': dict(type='number', minimum=-180, maximum=180, description='유한 경도 -180~180.')}
WAYPOINT_ID = s('여행에 추가한 경유지 ID.', pattern='^trip-waypoint-[a-f0-9]{32}$')
WAYPOINT_FIELDS = {key: CAR_PLACE_FIELDS[key] for key in ('name', 'lat', 'lng')}
WAYPOINT = strict(dict(WAYPOINT_FIELDS, id=WAYPOINT_ID), '이 여행에만 저장하는 코스 경유지.')
CAR_PLACE = strict(dict(CAR_PLACE_FIELDS, id=IDENT, addedBy=ACCOUNT, createdAt=TIME,
    selectedBy=arr(ACCOUNT, '보이는 탑승자의 선택. 계정 ID 순서.')), '운전자·탑승자·방장에게만 좌표·ID 제공.')
CAR_PLACE_SUMMARY = strict({'name': CAR_PLACE_FIELDS['name'], 'selectedBy': n('보이는 선택자 수.', minimum=0)},
    '다른 차 멤버에게는 이 두 필드만 제공.')
CAR_SIGNAL = strict({'id': IDENT, 'kind': s('합의한 손들기 장소.', enum=['signal']),
    'name': s('요청자가 공유한 장소 이름.', minLength=1, maxLength=80),
    'lat': CAR_PLACE_FIELDS['lat'], 'lng': CAR_PLACE_FIELDS['lng']}, '내 차 경로에서 현재 볼 수 있는 합의한 손들기 장소.')
CAR_SIGNAL_SUMMARY = strict({'kind': CAR_SIGNAL['properties']['kind'], 'name': CAR_SIGNAL['properties']['name'],
    'selectedBy': n('손들기 장소에는 픽업·드랍 선택자가 없음.', minimum=0, maximum=0)},
    '다른 차 멤버에게는 이름과 종류만 제공하며 ID·좌표는 제외.')
CAR_PLACES = arr(dict(oneOf=[CAR_PLACE, CAR_PLACE_SUMMARY, CAR_SIGNAL, CAR_SIGNAL_SUMMARY]),
    '차별 픽업·드랍과 합의한 손들기 장소. 픽업·드랍은 kind별 최대 10개, 차단 상대 제외.')
ROUTE_COURSE = strict({'type': s('코스 장소.', enum=['course']), 'ref': PACK, 'courseId': PACK, 'dropRef': IDENT},
    'courseId=packId, ref=stop ID. 같은 좌표 드랍은 선택적 dropRef로 합침.')
ROUTE_COURSE['required'] = ['type', 'ref', 'courseId']
ROUTE_PLACE = strict({'type': s('차 장소.', enum=['pickup', 'drop']), 'ref': IDENT}, 'ref=차별 place ID.')
ROUTE_SIGNAL = strict({'type': s('합의한 손들기 장소.', enum=['signal']), 'ref': IDENT},
    'ref=합의한 손들기 ID. 다른 여행·미합의·현재 숨겨진 장소 참조는 허용하지 않습니다.')
ROUTE_ITEMS = dict(arr(dict(oneOf=[ROUTE_COURSE, ROUTE_PLACE, ROUTE_SIGNAL]),
    '중복 금지, 조회 가능한 코스의 모든 장소 포함. 합의한 손들기는 현재 다음 목적지 앞에 한 번만 추가.'), maxItems=50)
RIDE_INVITE = strict({'id': IDENT, 'carId': IDENT, 'accountId': ACCOUNT, 'createdAt': TIME}, '운전자와 대상 본인에게만 표시.')
for model, fields in ((SUMMARY, dict(DATES, state=TRIP_STATE)),
        (DETAIL, dict(DATES, state=TRIP_STATE, locationConsent=LOCATION_CONSENT, revision=n('start/finish/cancel에 보내는 현재 여행 revision.', minimum=1),
            rideInvites=arr(RIDE_INVITE, '본인 관련 태우기 요청.'))),
        (CAR, dict(places=CAR_PLACES, routeOrder=nullable(ROUTE_ITEMS))),
        (COURSE, dict(stops=arr(STOP, '코스 장소와 그 도착 직전에 배치한 여행 경유지.'),
            waypoints=dict(arr(WAYPOINT, '여행에 추가한 경유지.'), maxItems=3),
            completedCarIds=arr(IDENT, '완료한 보이는 차 ID.')))):
    model['properties'].update(fields)
    model['required'].extend(fields)
CAR['properties']['routeNext'] = nullable(dict(ROUTE_ITEMS['items'],
    description='운전자 차량이 지금 향하는 장소. 운전자의 안내 보고(route-progress)나 서버의 합의 장소 삽입으로 정하고, 도착 확인 뒤 그 장소를 지났으면 다음 도착 대상으로 바뀜. 아직 설정하지 않았거나 그 장소가 현재 숨겨지면 필드 없음, null=경로 끝.'))
CAR['properties']['routeRevision'] = n('내 차 경로의 변경 번호. 기존 기록은 0이며 순서 변경·손들기 장소 추가 시 증가.', minimum=0, maximum=2147483647)
ROUTE_PLAN = strict({'contractVersion': n('명시적으로 시작한 구간 경로 계약.', minimum=2, maximum=2),
    'phase': s('서버 도착 보고로 결정한 내 차 구간.', enum=['pickup', 'waiting', 'shared', 'drop', 'done']),
    'segments': arr(strict({'segment': s('고정 구간 순서.', enum=['pickup', 'shared', 'drop']), 'items': ROUTE_ITEMS}, '픽업, 공유, 드랍 순서.'), '차별 고정 구간.'),
    'joinPoint': strict(dict(WAYPOINT_FIELDS, courseId=PACK, ref=PACK), '첫 공유 코스의 첫 장소.'),
    'joinEtaSeconds': dict(type='null', description='실제 경로 제공자 ETA가 없으므로 null.'),
    'progressRevision': n('서버 도착·경유지 삽입 진행 번호.', minimum=0, maximum=2147483647),
    'next': nullable(ROUTE_ITEMS['items']),
    'joinBarrier': strict({'arrivedCarIds': arr(IDENT, '현재 볼 수 있는 도착 차량 ID.'),
        'totalCarCount': n('출발 시 고정한 참여 차량 중 남은 차량 수.', minimum=0), 'released': b('모든 참여 차량 합류 도착.')}, '합류 장벽.'),
    'progress': nullable(strict({
        'remainingMeters': n('차에 탄 사람이 60초 안에 공유한 최신 위치에서 next까지의 직선 거리(m). 도로 거리·ETA 아님.', minimum=0),
        'legFraction': nullable(dict(type='number', minimum=0, maximum=1,
            description='직전 경로 항목→next 직선 위에 투영한 위치 비율(0~1, 소수 셋째 자리). 직전 항목이 없으면 null.'))},
        '진행 중 여행에서 next를 향하는 이 차의 실시간 위치. next 없음·합류 대기·단일 합류 코스 완료 대기·위치 공유 동의 없음·60초 넘은 위치면 null. 도착을 추론하지 않음.'))},
    'v2 시작 이후 현재 차 운전자·동승자에게 제공. 다른 차·v1·준비 중 경로에는 null. 위치에서 도착을 추론하지 않음.')
CAR['properties']['routePlan'] = nullable(ROUTE_PLAN)
CAR['required'].append('routePlan')
ROUTE_STATUS = strict({'phase': ROUTE_PLAN['properties']['phase'], 'joinEtaSeconds': dict(type='null', description='실제 ETA 근거 없음.'),
    'progress': nullable(strict({
        'target': dict(ROUTE_COURSE, description='pickup 단계는 합류 지점, shared 단계는 다음 공유 코스 장소. 개인 픽업·드랍·손들기 장소는 쓰지 않음.'),
        'remainingMeters': n('차에 탄 사람이 60초 안에 공유한 최신 위치에서 target까지의 직선 거리. 100m 단위로 반올림.', minimum=0),
        'legFraction': nullable(dict(type='number', minimum=0, maximum=1,
            description='shared 단계에서 직전 공유 코스 장소→target 직선 위 위치 비율(0~1, 소수 둘째 자리). pickup 단계·첫 장소는 null.'))},
        '진행 중 여행에서 공유 경로 기준 이 차의 대략 위치. waiting·drop·done, 위치 공유 동의 없음, 60초 넘은 위치면 null.'))},
    '현재 볼 수 있는 차 운전자가 명시 보고한 구간과 공유 경로 기준 대략 진행만 공유. 개인 장소·선택자·좌표·시각 없음.')
CAR['properties']['routeStatus'] = nullable(ROUTE_STATUS)
CAR['required'].append('routeStatus')
DETAIL['properties']['routeContractVersion'] = n('생략한 출발은 기존 계약 1, 명시한 출발은 구간 계약 2.', minimum=1, maximum=2)
DETAIL['required'].append('routeContractVersion')
START_CONFLICT = strict({
    'activeTrips': dict(arr(strict({'tripId': IDENT, 'title': TITLE, 'isOwner': b('요청자가 그 여행의 방장인지. true면 완료, false면 나가기로 정리합니다.')},
        '요청자가 참여 중인 다른 진행 중 여행.'), '최근에 시작한 여행부터. 규칙 도입 전 데이터는 여러 개일 수 있습니다. 비어 있지 않으면 시작은 endActiveTrip=true가 필요합니다.')),
    'busyMemberIds': dict(arr(ACCOUNT, '다른 진행 중 여행에 참여 중인 이 여행의 수락 멤버. 어느 여행인지는 공개하지 않습니다. '
        '요청자가 방장인 진행 중 여행에만 함께 있는 멤버는 그 여행을 완료하면 풀리므로 제외합니다.'), maxItems=19)},
    '준비 중 여행의 방장에게만 제공하는 시작 전 확인. busyMemberIds가 비어 있지 않으면 409 TRIP_MEMBER_ALREADY_ACTIVE입니다.')
DETAIL['properties']['startConflict'] = nullable(START_CONFLICT)
DETAIL['required'].append('startConflict')

P = '/v1/social/trips'
D = P + '/{id}'
CHAT = D + '/chat'
CHAT_TEXT = s('공백을 제거한 메시지 1~400자. 줄바꿈만 제어문자로 허용합니다.', minLength=1, maxLength=400)
CHAT_MESSAGE = strict(dict(id=IDENT, senderId=ACCOUNT, senderName=s('작성자의 현재 표시 이름.'),
    createdAt=TIME, text=CHAT_TEXT), '현재 보이는 참여자가 작성한 메시지.')
C = D + '/cars/{carId}'
L = '/v1/social/trip-links'
F = '/v1/social/friend-link'
FL = '/v1/social/friend-links'
NATIVE_TRIPS = {('get', P), ('get', D), ('post', D + '/respond')}
BODY = {
    ('post', CHAT): strict(dict(id=IDENT, text=CHAT_TEXT), '보낼 메시지와 브라우저가 만든 32자리 16진수 ID.'),
    ('post', P): strict({'title': TITLE, 'description': DESCRIPTION, 'memberIds': dict(arr(ACCOUNT, '생성자의 수락한 비차단 친구.'), maxItems=19, uniqueItems=True)}, '방장 포함 20명까지 초대.'),
    ('patch', D): strict({'title': TITLE, 'description': DESCRIPTION}, 'edit 권한으로 수정.'),
    ('post', D + '/members'): strict({'accountId': ACCOUNT}, '호출자의 수락한 비차단 친구 초대.'),
    ('post', D + '/respond'): strict({'accept': b('수락 또는 거절.')}, '본인 pending 초대에 응답.'),
    ('put', D + '/members/{accountId}/permissions'): PERMISSIONS,
    ('post', D + '/cars'): dict(strict(dict(CAR_FIELDS, remotePolicy=REMOTE_POLICY_INPUT), '차량 보유 멤버가 차 생성. remotePolicy 생략 시 꺼짐. 차량 native 생성에서는 remotePolicy를 받지 않습니다.'), required=['name', 'seats']),
    ('put', C + '/remote-policy'): REMOTE_POLICY_INPUT,
    ('patch', C): strict(CAR_FIELDS, '운전자만 차 수정.'),
    ('post', D + '/courses'): strict({'packId': PACK}, '수락한 여행 일행이 코스 첨부. 방장·edit 권한은 필요하지 않습니다.'),
    ('post', D + '/waypoints'): strict(dict(WAYPOINT_FIELDS, packId=PACK), '첨부한 코스의 도착 직전에 추가할 장소.'),
    ('put', D + '/courses/priority'): strict({
        'packIds': dict(arr(PACK, '화면에서 볼 수 있는 코스 ID를 원하는 순서로 모두 전송.'), minItems=2, maxItems=10, uniqueItems=True),
        'revision': n('화면에 표시된 여행 리비전.', minimum=1, maximum=2147483647)}, '준비 중 여행의 코스 순서 저장.')
}
BODY[('post', P)]['properties'].update(DATES)
BODY[('patch', D)]['properties'].update(DATES)
BODY[('patch', D)]['required'] = []
BODY[('patch', D)]['anyOf'] = [dict(required=['title', 'description']), dict(required=['startDate', 'endDate'])]
BODY[('patch', D)]['dependentRequired'] = {'title': ['description'], 'description': ['title']}
BODY[('patch', D)]['description'] += ' 제목·설명은 항상 함께, 또는 날짜 두 키만 수정. 400 Invalid trip dates.'
EMPTY_BODY = '업무 필드가 없습니다. 웹은 빈 본문 또는 {}만 받고 다른 키는 400입니다.'
# Their handlers accept an absent body as {} (body(optional=True), link_body), so the body is optional.
OPTIONAL_BODY = {('post', D + '/link'), ('put', C + '/ride'), ('post', F)}
for key in OPTIONAL_BODY:
    BODY[key] = dict(const={}, additionalProperties=False, description=EMPTY_BODY)
NO_BODY = set()
for path in (L + '/preview', L + '/join', FL + '/preview', FL + '/accept'):
    BODY[('post', path)] = strict({'token': TOKEN}, 'URL에 토큰을 넣지 않습니다. JSON 본문으로 전송하며 CSRF가 필요합니다.')
for path in (P, D + '/respond', L + '/join'):
    BODY['post', path]['properties']['locationConsent'] = dict(LOCATION_CONSENT, default=False)


def status(*values):
    return strict({'status': s('처리 결과.', enum=list(values))}, '변경 결과.')


def result(schema, code='200'):
    return {code: response(schema, '처리 결과.')}


OPS = {}
for method, path, title, effects, responses in [
    ('get', P, '내 여행과 초대', '보관 삭제하지 않은 수락 여행은 planned/active/completed/cancelled 모두 반환하고 state로 구분합니다. pending 초대는 planned/active만 반환합니다.', result(PAGE)),
    ('post', P, '여행 만들기', '방장은 생성 요청에서 내 위치 공유 여부를 선택합니다. false 또는 생략해도 여행을 생성합니다. 비친구 초대는 404 Account unavailable. 준비/진행 소유 20개 초과는 409 Trip limit reached.', result(strict({'id': IDENT}, '여행 ID.'), '201')),
    ('get', D, '여행 상세', '비멤버·pending은 404 Trip unavailable. 차단은 양방향으로 숨김. 통합 화면의 상태·역할·본인 공유 요약은 별도 GET /workspace에서 조회.', result(DETAIL)),
    ('patch', D, '여행 수정', '방장 또는 edit 필요. 없으면 403 Trip edit permission required.', result(status('updated'))),
    ('delete', D, '여행 삭제', '방장만 가능. 종료/취소 여행에 deleted_at을 설정하고 채팅을 삭제합니다. 여행 기록은 보존합니다. 준비/진행은 409 Close the trip before deleting it. 403 Only the owner may manage the trip.', result(status('deleted'))),
    ('post', D + '/members', '친구 초대', '방장·invite 필요. 비친구·차단 404 Account unavailable. pending 포함 20명, 409 Trip is full.', {**result(status('pending'), '201'), **result(status('pending', 'accepted'))}),
    ('post', D + '/respond', '초대 응답', '수락할 때 내 위치 공유 여부를 선택합니다. false 또는 생략하면 공유를 끈 채 참여합니다. 거절하면 대기 멤버십을 삭제합니다. 중복 수락은 가입 시각·역할·공유 선택을 보존합니다. 진행 중 여행 초대는 다른 진행 중 여행에 참여 중이면 409 TRIP_ALREADY_ACTIVE입니다.', result(status('accepted', 'declined'))),
    ('get', C + '/remote-policy', '동승자 리모컨 허용 조회', '운전자 또는 해당 차에 현재 탄 수락 멤버가 조회합니다.', result(REMOTE_POLICY_RESULT)),
    ('put', C + '/remote-policy', '동승자 리모컨 미리 허용', '운전자만 준비·진행 중 차의 설정을 변경합니다. 기본 꺼짐. deviceId 생략 시 유일한 현재 연결 차량 선택. 정책 변경은 대기 명령을 취소하고 trip detail을 무효화합니다.', result(REMOTE_POLICY_RESULT)),
    ('delete', D + '/members/{accountId}', '제거 또는 탈퇴', '방장은 누구나 제거, 일반 멤버는 본인만. 방장 탈퇴 409 Finish or cancel the trip instead. 차·좌석·본인 코스·대기 요청 정리.', result(status('removed'))),
    ('put', D + '/members/{accountId}/permissions', '멤버 권한', '방장만. 대상은 방장 외 수락 멤버.', result(status('updated'))),
    ('post', D + '/link', '여행 링크 발급', '방장·invite 필요. 기존 링크 교체, 7일 만료.', result(LINK, '201')),
    ('delete', D + '/link', '여행 링크 철회', '방장·invite 필요.', result(status('revoked'))),
    ('post', L + '/preview', '여행 링크 미리보기', '알 수 없음·만료·방장 차단은 404 Link unavailable.', result(PREVIEW)),
    ('post', L + '/join', '여행 링크 참여', '링크로 참여할 때 내 위치 공유 여부를 선택합니다. false 또는 생략해도 참여합니다. 이미 참여한 사람의 가입 시각과 공유 선택은 유지합니다. 만원이면 409 Trip is full. 진행 중 여행 링크는 다른 진행 중 여행에 참여 중이면 409 TRIP_ALREADY_ACTIVE입니다.', result(strict({'tripId': IDENT}, '참여한 여행.'))),
    ('post', F, '친구 링크 발급', '본인 링크 교체, 7일 만료.', result(LINK, '201')),
    ('delete', F, '친구 링크 철회', '본인 링크 철회.', result(status('revoked'))),
    ('post', FL + '/preview', '친구 링크 미리보기', '알 수 없음·만료·차단은 404 Link unavailable. 본인 링크는 alreadyFriends=false.', result(FRIEND_PREVIEW)),
    ('post', FL + '/accept', '친구 링크 수락', '양쪽 친구 관계를 accepted로 저장. 본인 링크 수락은 404 Link unavailable. 링크는 다른 사람에게 계속 유효. 계정은 생성하지 않음.', result(status('accepted'))),
    ('post', D + '/cars', '차 만들기', '현재 vehicle 아니면 409 Vehicle owner required. 이미 운전 중 409 Already driving. 동승 좌석과 대기 요청 해제.', result(strict({'id': IDENT}, '차 ID.'), '201')),
    ('patch', C, '차 수정', '운전자만 가능. 현재 동승자 미만 좌석은 409 Seats taken.', result(status('updated'))),
    ('delete', C, '차 삭제', '운전자 또는 방장. 동승자는 미배정, 차의 대기 요청 삭제.', result(status('deleted'))),
    ('put', C + '/ride', '차 탑승·이동', '수락 멤버, 운전 중이면 409 Already driving. 만석은 409 Car is full. 이동 시 이전 대기 요청 제거.', result(status('riding'))),
    ('delete', D + '/ride', '차 내리기', '좌석과 내 대기 요청 해제.', result(status('left'))),
    ('post', D + '/courses', '코스 첨부', '수락한 일행 누구나 본인 코스 또는 공개 코스를 추가합니다. 준비·진행 중 여행만 가능합니다. 404 Course unavailable, 10개 초과 409 Trip course limit. 중복은 200.', {**result(status('added'), '201'), **result(status('added'))}),
    ('delete', D + '/courses/{packId}', '코스 제거', '방장·edit 또는 추가한 본인. 원코스는 보존.', result(status('removed'))),
    ('post', D + '/waypoints', '여행 경유지 추가', '방장 또는 edit 권한, 준비 중 여행만 가능. 여행에 담긴 코스마다 최대 3곳을 도착 전에 추가. 동일 장소는 200으로 기존 ID 반환.', {**result(WAYPOINT, '201'), **result(WAYPOINT)}),
    ('delete', D + '/waypoints/{packId}/{waypointId}', '여행 경유지 제거', '방장 또는 edit 권한, 준비 중 여행만 가능. 원본 코스는 유지.', result(status('removed'))),
    ('put', D + '/courses/priority', '코스 순서 저장', '방장 또는 edit 권한, 준비 중 여행만 가능. 여행 상태·리비전·코스 목록 변경은 409.', result(strict({
        'status': s('처리 결과.', enum=['updated']), 'revision': n('저장된 여행 리비전.', minimum=1, maximum=2147483647)}, '순서 저장 결과.'))),
]:
    native = (method, path) in NATIVE_TRIPS
    prerequisites = ('웹은 팀 세션, 차량은 같은 인증서의 mTLS와 Bearer 및 기능 권한이 필요합니다.'
        if native else READ if method == 'get' else BROWSER)
    OPS[(method, path)] = entry('여행', title, prerequisites,
        '여행 화면 또는 공유 링크에서 호출합니다. 본문 없는 쓰기는 빈 본문 또는 {}.', effects,
        ('웹은 팀 세션, 차량은 현재 기기 인증과 기능 권한이 필요합니다. ' if native
            else '브라우저 팀 세션만 허용합니다. 차량 호출은 ' + ('403' if path.startswith((P, L)) else '404') + '입니다. ')
        + '웹 쓰기는 Origin/CSRF, 모든 쓰기는 계정별 분당 60회 제한. 모든 응답 private, no-store. '
        '정확한 JSON 키만 허용하며 그 외 400. 변경은 영향을 받는 멤버에 friends 알림. '
        '친구 해제는 여행 멤버십을 보존하며 대기 리모컨 요청을 정리. 방장과 차단 관계인 멤버는 제거.',
        responses, ['400', '401', '403', '404', '409', '413', '429', '503'])

OPS['post', D + '/respond']['example'] = dict(accept=True, locationConsent=False)
OPS['patch', D]['example'] = dict(title='우리 여행', description='', startDate=None, endDate=None)

OPS['get', CHAT] = entry('여행', '여행 채팅 읽기', READ,
    '수락한 참여자가 여행 상세에서 채팅을 엽니다.',
    '최근 50개 안에서 현재 보이는 수락 참여자의 메시지를 오래된 순서부터 읽습니다. 차단 상대는 양방향으로 제외하고 삭제한 여행은 404입니다.',
    '브라우저 개인 세션만 허용합니다. 응답은 private, no-store입니다.',
    result(strict(dict(messages=dict(arr(CHAT_MESSAGE, '현재 볼 수 있는 최근 메시지.'), maxItems=50)), '여행 채팅.')),
    ['401', '403', '404', '503'])
OPS['post', CHAT] = entry('여행', '여행 채팅 전송', BROWSER,
    '준비 또는 진행 중인 여행의 수락 참여자가 메시지를 전송합니다.',
    '서버가 작성자와 작성 시각을 지정하고 본문을 암호화해 최근 50개를 보관합니다. 채팅 이벤트는 본문 없이 변경 버전만 전달합니다.',
    '전송 확인이 유실되면 같은 ID와 본문으로 다시 보냅니다. 보관 중인 ID에 다른 본문을 쓰면 409입니다. 최대 4 KiB, 계정별 여행 변경 분당 60회 제한, private, no-store.',
    result(strict(dict(id=IDENT, createdAt=TIME), '저장된 메시지 ID와 서버 시각.'), '201'),
    ['400', '401', '403', '404', '409', '413', '429', '503'], example=dict(id='a' * 32, text='여기서 만나요.'))
# The trip list only reads the caller's memberships; it has no state conflict.
OPS['get', P]['errors'] = [code for code in OPS['get', P]['errors'] if code != '409']
