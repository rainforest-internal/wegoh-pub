from api_doc_shared import entry, response, obj, s, n, b, arr, nullable, IDENT, ACCOUNT, TIME, BROWSER, READ
from api_doc_trips import strict, TITLE, DESCRIPTION, PERSON, CAR_FIELDS, LOCATION_CONSENT, result

T = '/v1/social/trips/{id}'
REVISION = n('현재 조회의 변경 번호.', minimum=1, maximum=2147483647)
ROLE = s('차 배정과 독립적인 역할.', enum=['member', 'dj', 'food', 'rest'])
SHARING = strict({key: b('본인이 선택하는 ' + key + ' 공유 동의.') for key in
    ('status', 'location', 'visits', 'music', 'voice', 'control')}, '6개 키를 모두 보내며 자동 동의하지 않습니다.')
PLACE = strict({'name': s('요청자가 고른 장소 이름. 같은 여행 멤버에게 검토 없이 그대로 보입니다.', minLength=1, maxLength=80),
    'latitude': dict(type='number', minimum=-90, maximum=90, description='공유한 위도.'),
    'longitude': dict(type='number', minimum=-180, maximum=180, description='공유한 경도.')}, '명시적으로 공유한 장소.')
KINDS = s('일반 멤버가 보낼 수 있는 신호.', enum=['restroom', 'smoking', 'nursing', 'drowsy', 'rest', 'hungry', 'cafe', 'ev_charge', 'fuel', 'arrived', 'join'])
STATE = s('소유자가 전환하는 여행 상태.', enum=['planned', 'active', 'completed', 'cancelled'])
FEATURE = strict({'available': b('해당 trip 경로가 등록되고 현재 상태에서 이용 가능한지.'),
    'consentRequired': b('본인 여행 공유 동의가 필요한지. 기기 허가와 개별 미션/주행 동의는 해당 API에서 따로 확인.')}, '기능 내용이나 다른 기기 허가는 포함하지 않습니다.')
WORKSPACE = strict({'tripId': IDENT, 'revision': REVISION, 'state': STATE, 'startedAt': nullable(TIME),
    'endedAt': nullable(TIME), 'title': TITLE, 'description': DESCRIPTION,
    'myPermissions': strict({key: b('본인의 ' + key + ' 권한.') for key in ('owner', 'invite', 'edit')}, '현재 권한.'),
    'members': arr(strict(dict(PERSON['properties'], isOwner=b('소유자.'), isMe=b('본인.')), '보이는 수락 멤버.'), 'pending과 차단 상대는 제외.'),
    'cars': arr(strict(dict(CAR_FIELDS, id=IDENT, driverId=ACCOUNT, passengers=arr(ACCOUNT, '보이는 동승자 ID.')), '보이는 운전자의 차.'), '위치·리모컨 허가를 포함하지 않는 차 요약.'),
    'roles': arr(strict({'accountId': ACCOUNT, 'role': ROLE}, '보이는 멤버의 역할.'), '타인의 공유 동의는 제외.'),
    'mySharing': {'description': '본인 설정. 차량에는 이 경로에서 허용된 status/location만 반환.',
        'anyOf': [SHARING, strict({key: SHARING['properties'][key] for key in ('status', 'location')}, '차량에는 status/location만 반환.')]},
    'features': strict({key: FEATURE for key in ('signals', 'places', 'music', 'voice', 'missions', 'drivingData', 'reports', 'results')}, '미완성 서비스는 available=false.')},
    '내부 room ID·코드·만료, 위치·속도·음악·음성 상대·개인 기록을 포함하지 않는 통합 상세.')
SIGNAL = strict({'id': IDENT, 'accountId': ACCOUNT, 'kind': KINDS, 'destination': nullable(PLACE),
    'createdAt': TIME, 'revision': REVISION, 'contextState': s('진행 중 명단/동의/역할 변경 뒤 새 신호로 재확인. 종료한 직접 요청의 결과는 보존.', enum=['valid', 'reconfirm']),
    'votes': strict({'agree': n('현재 viewer에게 보이는 찬성 수.', minimum=0), 'pass': n('현재 viewer에게 보이는 보류 수.', minimum=0)}, '가입 세대와 문맥이 유효한 투표만 계산.'),
    'myVote': nullable(s('내 현재 선택.', enum=['agree', 'pass'])), 'agreed': b('새 손들기는 요청 그룹을 제외한 모든 차 그룹의 동의 결과. 이전 손들기는 기존 운전자 과반, 기존 장소 제안은 기존 참여자 합의를 따릅니다. 내비 적용 결과는 아닙니다.'),
    'inProgress': b('여행의 현재 진행 중인 손들기 한 건이면 true.'),
    'resolution': s('새 그룹 요청은 전 그룹 응답 전 pending, 전부 동의하면 agreed, 하나라도 거절하면 passed. completed/cancelled=요청자 종료, reconfirm=문맥 종료. 이전 요청의 과반 결과는 보존.',
        enum=['pending', 'agreed', 'passed', 'completed', 'cancelled', 'reconfirm']),
    'driverVotes': strict({'agree': n('요청자가 운전자이면 암묵적 동의 한 표를 포함한 현재 운전자 동의 수.', minimum=0),
        'pass': n('현재 운전자의 다음에 표 수.', minimum=0), 'total': n('같은 운전자의 여러 차를 중복 계산하지 않은 운전자 수.', minimum=0)},
        '이전 요청의 운전자 집계. 차단한 상대의 표와 인원은 제외하며 전체 여행의 결정은 resolution으로 확인합니다. 새 그룹 합의 판단에는 사용하지 않습니다.')}, '현재 공유/차단을 거른 신호.')
SIGNAL['properties'].update({
    'candidateDetails': nullable(strict({'routeName': nullable(s('후보 조회 때 공식 원자료의 노선명.', maxLength=100)),
        'direction': nullable(s('후보 조회 때 공식 원자료의 방향 원문.', maxLength=80)),
        'fromLeadMeters': nullable(n('후보 조회 당시 맨 앞 차로부터의 경로 거리.', minimum=0, maximum=2147483647)),
        'detourSeconds': nullable(n('후보 조회 당시 추가 소요시간 추정. 음수도 보존.', minimum=-2147483647, maximum=2147483647))},
        '서버가 발급한 선택 영수증을 검증한 메타데이터. 실시간 거리·시간이나 도착 인증이 아닙니다. 과거·직접 장소 요청이면null.')),
    'decisionRule': s('새 장소 요청에 적용하는 차량 그룹 합의 규칙. 없는 기록은 기존 규칙으로 해석.', enum=['other-car-groups-v1']),
    'requesterCarId': IDENT,
    'groupVotes': strict({'agree': n('동의한 차 그룹 수.', minimum=0),
        'pass': n('거절한 차 그룹 수.', minimum=0),
        'total': n('요청 그룹을 제외한 응답 대상 차 그룹 수.', minimum=0)},
        '차단 필터와 무관한 전체 응답 대상의 집계이며 각 그룹의 첫 응답을 한 표로 계산. 최종 결과는 resolution을 사용.'),
    'myGroupChoice': nullable(s('내 차 그룹에서 확정한 첫 응답.', enum=['agree', 'pass'])),
    'canRespond': b('현재 내가 응답 대상 차 그룹에 속하고 그 그룹의 첫 응답을 보낼 수 있는지.'),
    'groupResponses': arr(strict({'carId': IDENT, 'carName': s('요청 시점에 저장한 응답 대상 차 그룹 이름.'),
        'choice': nullable(s('해당 그룹의 첫 응답. null이면 답변 대기.', enum=['agree', 'pass'])),
        'responderAccountId': nullable(ACCOUNT), 'responderName': nullable(s('첫 응답자 이름. 대기 또는 차단 관계면 null.')),
        'responseSource': nullable(s('서버가 실제 응답 요청에서 기록한 클라이언트. 과거·대기·차단 응답자는 null.', enum=['native', 'iphone', 'web']))}, '현재 viewer에게 보이는 그룹별 응답 상태.'),
        '대기 중에도 표시하며 거절한 차 이름을 안내할 수 있습니다. 차단 상대는 노출하지 않습니다.')})
PROPOSAL = strict({'id': IDENT, 'accountId': ACCOUNT, 'category': s('담당 목록.', enum=['food', 'rest']),
    'place': PLACE, 'state': s('일정 선택과 담당자 추천은 별도.', enum=['proposed', 'selected']),
    'recommended': b('해당 담당자가 후보 목록에 추천한 표시.'), 'selectedBy': nullable(ACCOUNT),
    'sourceSignalId': IDENT, 'revision': REVISION, 'createdAt': TIME}, '철회·재가입 전 원문은 공개되지 않습니다.')
CURSOR = nullable(s('다음 페이지 cursor. 첫 페이지는 생략.', pattern='^(0|[1-9][0-9]{0,4})$'))
CHANGED = strict({'status': s('처리 결과.', enum=['updated', 'withdrawn']), 'revision': REVISION}, '현재 변경 번호.')
LOCATION_SHARING = strict({'locationConsent': LOCATION_CONSENT, 'locationShareId': nullable(IDENT), 'revision': REVISION},
    '본인의 여행 위치 공유 선택. locationShareId는 현재 공유를 켠 기간의 식별자이고 꺼져 있으면 null입니다.')
VOICE_REVISION = n('이 계정과 여행의 음성 참여 변경 번호. 여행·손들기 revision과 독립적입니다.', minimum=1, maximum=2147483647)
VOICE_PARTICIPATION = strict({'tripId': IDENT, 'participating': b('현재 계정이 이 여행의 워키토키에 참여하는지.'),
    'memberJoinedAt': TIME, 'revision': VOICE_REVISION}, '진행 중인 여행의 본인 참여 설정. 기기 마이크 허용과 별도입니다.')
BODY = {
    ('put', T + '/members/{accountId}/role'): strict({'role': ROLE, 'revision': REVISION}, '소유자만 수락 멤버의 역할 지정.'),
    ('patch', T + '/sharing'): strict({'consents': SHARING}, '본인 공유 선택. location:false로 철회할 수 있습니다. 일행 전체에 위치 공유를 켜려면 location-sharing을 사용합니다. 종료·탈퇴 뒤에는 끄는 방향만 허용.'),
    ('patch', T + '/location-sharing'): strict({'locationConsent': LOCATION_CONSENT},
        '여행 참여를 유지하면서 일행에게 내 위치를 공유하거나 철회합니다.'),
    ('patch', T + '/voice-participation'): strict({'participating': VOICE_PARTICIPATION['properties']['participating'],
        'memberJoinedAt': TIME, 'revision': VOICE_REVISION}, '직전 조회의 가입 시각과 음성 revision으로 본인의 참여 한 항목만 변경합니다.'),
    ('post', T + '/signals'): dict(strict({'kind': KINDS, 'destination': nullable(PLACE),
        'candidateReceipt': s('선택 후보의 서버 인증 영수증. 300초/계정/여행/리비전/종류/장소가 다르면409 TRIP_SIGNAL_CANDIDATE_CHANGED.', maxLength=2048, pattern='^[A-Za-z0-9_-]+$')},
        '진행 중 여행의 현재 참여자. 새 요청은 장소 유무와 관계없이 지속적인 상태·위치 공유 동의와 별개인 명시적 행동입니다. 장소 요청은 현재 차 배정이 필요하며 없으면 409 TRIP_SIGNAL_CAR_REQUIRED, 차단 관계로 응답할 사람이 없는 대상 그룹이 있으면 409 TRIP_SIGNAL_GROUP_UNREACHABLE입니다. 이전에 저장한 요청은 기존 공유 규칙을 유지합니다. 진행 중 손들기는 한 건이고 이미 있으면 409 TRIP_SIGNAL_IN_PROGRESS입니다. 같은 작성자의 같은 진행 중 요청 재시도는 같은 ID를 반환합니다.'), required=['kind']),
    ('post', T + '/signals/{signal}/vote'): strict({'choice': s('동의 또는 거절.', enum=['agree', 'pass'])},
        '새 그룹 요청은 요청 그룹을 제외한 각 차의 운전자·동승자 중 첫 응답을 확정하며 변경·철회할 수 없습니다. 같은 차의 추가 응답은 200 already=true와 최초 choice·responderAccountId를 반환하며 최초 응답을 바꾸지 않습니다. 현재 탑승·가입 세대와 차단 관계를 다시 검사합니다. 모든 대상 그룹의 응답 뒤 결과를 결정합니다. 재확인 필요이면 409 후 새 신호로 제안.'),
    ('post', T + '/signals/{signal}/finish'): strict({'result': s('요청자가 진행 중 요청을 마친 결과.',
        enum=['completed', 'cancelled'])}, '작성자만 종료합니다. 장소가 있는 요청을 직접 completed로 바꿀 수 없으며 해당 요청의 합의 규칙으로 결정합니다. 취소는 작성자가 할 수 있습니다.'),
    ('post', T + '/places'): dict(strict({'category': PROPOSAL['properties']['category'], 'place': PLACE,
        'sourceSignalId': IDENT}, '해당 food/rest 담당자가 생성. 직접 place 또는 현재 보이는 sourceSignalId 하나만 선택. 원 작성자·가입 세대·공유 동의는 보존.'),
        required=['category'], oneOf=[{'required': ['place'], 'not': {'required': ['sourceSignalId']}},
            {'required': ['sourceSignalId'], 'not': {'required': ['place']}}]),
    ('patch', T + '/places/{proposal}'): dict(strict({'revision': REVISION, 'place': PLACE, 'recommended': b('담당자의 추천 표시.'),
        'state': s('본인 철회 또는 소유자/edit의 일정 선택.', enum=['proposed', 'selected', 'withdrawn'])},
        'revision과 최소 한 변경 필드. 타인의 원문 수정 금지. 선택된 장소 수정 전 소유자/edit가 선택 해제.'), required=['revision']),
    ('delete', T + '/places/{proposal}'): strict({'revision': REVISION}, '작성자 본인의 후보 철회.'),
    ('patch', T + '/signals/{signal}/review-request'): strict({'consent': b('장소 이름 검토 요청 또는 철회.')}, '작성자만 기존 room-place 검토 사용.'),
    ('post', T + '/signals/{signal}/reports'): strict({'reason': s('기존 콘텐츠 신고 사유.')}, '현재 공개된 장소 이름 신고.')
}
for action in ('start', 'finish', 'cancel'):
    BODY[('post', T + '/' + action)] = strict({'revision': REVISION}, '소유자만 상태 전환. 같은 전환 재요청은 현재 결과.')
BODY[('post', T + '/start')]['properties']['routeContractVersion'] = n('2를 명시한 새 여행만 픽업·합류·공유·드랍 계약 사용. 생략은 기존 계약 유지.', minimum=2, maximum=2)
BODY[('post', T + '/start')]['properties']['endActiveTrip'] = dict(b('true면 시작 전에 요청자의 다른 진행 중 여행을 정리합니다. '
    '요청자가 방장인 여행은 완료(finish와 같은 결과·점수 확정, 방 정리)하고, 참여자인 여행에서는 나갑니다. 생략은 false.'), default=False)
NO_BODY = {('delete', T + '/signals/{signal}/vote')}
NATIVE = {('get', T + '/workspace'), ('get', T + '/signals'), ('post', T + '/signals'),
    ('post', T + '/signals/{signal}/vote'), ('post', T + '/signals/{signal}/finish'),
    ('delete', T + '/signals/{signal}/vote'), ('get', T + '/places')}
OPS = {}
for method, suffix, title, schema, code in [
    ('get', '/workspace', '여행 통합 상세', WORKSPACE, '200'),
    *[('post', '/' + action, title, strict({'tripId': IDENT, 'state': STATE, 'revision': REVISION,
        'startedAt': nullable(TIME), 'endedAt': nullable(TIME)}, '전환 결과.'), '200')
        for action, title in (('start', '여행 시작'), ('finish', '여행 종료'), ('cancel', '여행 취소'))],
    ('put', '/members/{accountId}/role', '여행 역할 지정', CHANGED, '200'),
    ('patch', '/sharing', '내 여행 공유 설정', strict({'consents': SHARING, 'revision': REVISION}, '저장한 본인 동의.'), '200'),
    ('get', '/location-sharing', '내 여행 위치 공유 조회', LOCATION_SHARING, '200'),
    ('patch', '/location-sharing', '내 여행 위치 공유 변경', LOCATION_SHARING, '200'),
    ('get', '/voice-participation', '내 여행 워키토키 참여 조회', VOICE_PARTICIPATION, '200'),
    ('patch', '/voice-participation', '내 여행 워키토키 참여 변경', VOICE_PARTICIPATION, '200'),
    ('get', '/signals', '여행 신호 목록', strict({'signals': arr(SIGNAL, '현재 페이지의 보이는 신호.'), 'nextCursor': CURSOR,
        'hasActiveSignal': b('현재 페이지나 차단 필터와 무관하게 이 여행에 진행 중인 손들기가 있는지. 작성자나 ID는 추가 공개하지 않습니다.')}, '최대 100개씩 조회.'), '200'),
    ('post', '/signals', '여행 신호 보내기', strict({'id': IDENT, 'status': s('sent', enum=['sent'])}, '새 신호.'), '201'),
    ('post', '/signals/{signal}/vote', '여행 신호 투표', dict(strict({'status': s('saved', enum=['saved']), 'choice': s('최초 저장한 선택.', enum=['agree', 'pass']),
        'already': b('같은 차의 응답이 이미 확정된 경우 true.'), 'responderAccountId': nullable(ACCOUNT)}, '투표 결과.'), required=['status','choice']), '200'),
    ('delete', '/signals/{signal}/vote', '여행 투표 철회', strict({'status': s('withdrawn', enum=['withdrawn']), 'choice': {'type': 'null', 'description': '철회 후 선택 없음.'}}, '철회 결과.'), '200'),
    ('post', '/signals/{signal}/finish', '내 손들기 완료 또는 취소', strict({'status': s('요청자가 고른 종료 결과.',
        enum=['completed', 'cancelled']), 'revision': REVISION}, '같은 종료 요청의 재시도는 동일 결과를 반환합니다.'), '200'),
    ('get', '/places', '여행 장소 후보 목록', strict({'places': arr(PROPOSAL, '현재 페이지의 보이는 후보.'), 'nextCursor': CURSOR}, '최대 100개씩 조회.'), '200'),
    ('post', '/places', '담당 장소 후보 추가', PROPOSAL, '201'),
    ('patch', '/places/{proposal}', '후보 정리 또는 일정 선택', CHANGED, '200'),
    ('delete', '/places/{proposal}', '내 장소 후보 철회', CHANGED, '200'),
    ('patch', '/signals/{signal}/review-request', '여행 장소 이름 검토 요청', strict({'state': s('검토 상태.'), 'requested': b('요청 여부.'), 'checksum': nullable(s('원문 checksum.'))}, '내부 방 키를 제외한 검토 상태.'), '200'),
    ('post', '/signals/{signal}/reports', '여행 장소 이름 신고', strict({'reportId': IDENT, 'state': s('quarantined', enum=['quarantined'])}, '재격리 결과.'), '202')
]:
    path = T + suffix
    native = (method, path) in NATIVE
    OPS[(method, path)] = entry('여행', title, READ if method == 'get' else BROWSER,
        '선택한 여행 ID만 사용합니다. 다른 여행의 하위 ID는 404입니다.',
        'pending/비멤버 404, 동의/역할 부족 403, 상태/revision 충돌 409. '
        '가입 세대·명단·동의 변경 후 이전 투표로 자동 합의하지 않습니다. 철회 후 재동의가 옛 공유를 복원하지 않습니다.',
        ('차량은 rooms:read 및 쓰기에는 rooms:interact와 functionalRevision 필요. '
            if native else '웹 전용. 차량 호출은 403. ') +
        '409이면 정본을 다시 읽습니다. private, no-store. 4 KiB와 정확한 JSON 키 제한. '
        '목록은 limit=1..100, cursor=직전 nextCursor(기본 50). 신호/후보 저장 5000개 상한.',
        {code: response(schema, '현재 viewer 기준의 응답.')}, ['400', '401', '403', '404', '409', '413', '429', '503'])

OPS[('post', T + '/places')]['example'] = dict(category='food', place=dict(name='직접 선택한 장소', latitude=0, longitude=0))
OPS[('patch', T + '/places/{proposal}')]['example'] = dict(revision=1, recommended=False)
for method in ('get', 'patch'):
    OPS[(method, T + '/voice-participation')]['effects'] = (
        '음성 서비스가 활성화된 진행 중 여행의 수락 멤버 본인만 사용합니다. '
        'participating만 수정하며 위치·음악 등 다른 공유 선택과 기기별 허용은 확대하지 않습니다. '
        '가입 문맥이나 revision이 바뀌면 409 TRIP_VOICE_PARTICIPATION_CHANGED이며 다시 읽고 자동 재시도하지 않습니다. '
        '같은 값은 revision을 올리지 않습니다. 끄면 현재 음성 연결과 기존 차량별 여행 음성 허용도 철회합니다.')
OPS[('post', T + '/start')]['effects'] += (
    ' 한 사람은 진행 중 여행 하나에만 참여합니다. 요청자가 다른 진행 중 여행에 참여 중이면 409 TRIP_ALREADY_ACTIVE이며, '
    'endActiveTrip=true로 다시 요청하면 그 여행을 정리한 뒤 같은 트랜잭션에서 시작합니다. '
    '다른 수락 멤버가 다른 진행 중 여행에 참여 중이면 409 TRIP_MEMBER_ALREADY_ACTIVE입니다. 요청자가 방장인 여행에만 함께 있는 멤버는 그 여행을 완료하면 풀리므로 제외합니다. '
    '대상 정보는 여행 상세 startConflict에서 확인합니다. 준비 중 여행 참여·초대 수락에는 제한이 없습니다.')
OPS[('post', T + '/signals')]['effects'] += (
    ' active 여행만(409 TRIP_STATE_CONFLICT). 알 수 없는 kind는 400 Invalid status signal. 손들기 장소 종류가 아닌 신호는 status 공유 동의, 장소가 있으면 location 동의도 필요(403 Sharing permission required). '
    '진행 중 손들기가 있으면 409 TRIP_SIGNAL_IN_PROGRESS, 장소 요청인데 내 차 배정이 없으면 409 TRIP_SIGNAL_CAR_REQUIRED, 응답할 사람이 없는 차 그룹이 있으면 409 TRIP_SIGNAL_GROUP_UNREACHABLE, '
    'v2 여행에서 내 차 경로가 끝났으면 409 TRIP_SIGNAL_ROUTE_FINISHED, 후보 영수증이 맞지 않으면 409 TRIP_SIGNAL_CANDIDATE_CHANGED, 여행당 5000개 상한은 409 Trip signal limit reached. '
    '계정별 분당 20회. 응답 대상 그룹이 없으면 바로 agreed로 경로에 반영하고, 대기 중이면 응답 대상에게 알림을 보냅니다.')
OPS[('post', T + '/signals/{signal}/vote')]['effects'] += (
    ' active 여행만. choice가 agree/pass가 아니면 400 Invalid vote. 새 그룹 요청에서 응답 대상 차 그룹이 아니면 403 TRIP_SIGNAL_OTHER_GROUP_REQUIRED, 진행 중 손들기가 아니면 409 TRIP_SIGNAL_NOT_ACTIVE, '
    '문맥이 바뀌었으면 409 TRIP_SIGNAL_RECONFIRM_REQUIRED. 마지막 그룹이 동의하면 그 장소를 각 차 경로에 넣습니다. 이전 규칙의 손들기는 현재 운전자만 응답합니다(403). 계정별 분당 30회.')
OPS[('post', T + '/signals/{signal}/finish')]['effects'] += (
    ' active 여행의 요청자만(403 Only the requester may finish a hand raise). result가 completed/cancelled가 아니면 400 Invalid hand-raise result. '
    '이미 같은 결과면 그대로 200, 진행 중 손들기가 아니면 409 TRIP_SIGNAL_NOT_ACTIVE, 장소 요청을 completed로 끝내려 하면 409 Drivers must decide on the selected place.')
OPS[('delete', T + '/signals/{signal}/vote')]['effects'] += (
    ' 새 그룹 요청의 첫 응답은 철회할 수 없으며 409 TRIP_SIGNAL_GROUP_RESPONSE_FINAL입니다. 200 철회는 기존 규칙의 요청에만 적용합니다.')

from copy import deepcopy
from api_doc_shared import ref, NATIVE as NATIVE_AUTH
from api_doc_vehicle import BODY as VEHICLE_BODY, MODELS as VEHICLE_MODELS
from api_doc_device_commands import BODY as COMMAND_BODY, MODELS as COMMAND_MODELS
from api_doc_friend_remotes import COMMAND as TRIP_REMOTE_COMMAND, TRIP_REMOTES
from device_command_registry import DRIVER_AREA

SAVED_MUSIC = '/v1/social/trips/{trip}/music/saved-playlists'
SAVED_MUSIC_ITEM = strict(dict(id=IDENT, title=s('공유한 곡 제목.', maxLength=120),
    url=s('원래 음악 서비스의 HTTPS 링크.', format='uri', maxLength=2048), addedBy=PERSON,
    reviewState=s('본인의 검토 진행 상태. 다른 참여자는 승인된 링크만 조회합니다.',
                  enum=['private', 'quarantined', 'approved', 'rejected'])), '여행에 추가한 링크 한 건.')
SAVED_MUSIC_PLAYING = strict(dict(itemId=IDENT, startedBy=PERSON,
    startedAt=s('차량에서 이 항목을 연 서버 시각입니다.', format='date-time')),
    '여행 멤버의 차량이 마지막으로 연 여행 플레이리스트 항목. 외부 음악 앱의 실제 재생 상태가 아닙니다.')
SAVED_MUSIC_LIST = strict(dict(tripId=IDENT, items=arr(SAVED_MUSIC_ITEM, 'DJ나 여행 소유자가 정한 재생 순서의 보이는 링크. 새 항목은 끝에 붙습니다.'),
    limit=n('수록 한도.', const=200), canAdd=b('여행에 항목을 더 추가할 공간이 있는지.'),
    canReorder=b('현재 DJ이거나 여행 소유자라서 순서를 바꿀 수 있는지.'),
    nowPlaying=arr(SAVED_MUSIC_PLAYING, '멤버별 최근 차량 재생. 보이는 항목과 차단하지 않은 멤버만, 최근 순입니다.')),
    '여행 하나의 단일 음악 목록. 차량·iPhone·웹이 같은 항목을 같은 순서로 받습니다. 내 보관함에서 고른 곡과 직접 추가한 곡 링크(POST /music/playlist)를 함께 담으며, '
    '직접 추가한 링크는 본인의 여행 음악 공유 동의가 있고 차량이면 room-music:read 목적도 승인됐을 때만 포함합니다. 차단 상대가 추가한 항목은 제외합니다.')
SAVED_MUSIC_POSITION = SAVED_MUSIC + '/{item}/position'
NOW_PLAYING = '/v1/social/trips/{trip}/music/now-playing'
BODY[('post', SAVED_MUSIC)] = strict(dict(playlistId=IDENT, playlistRevision=REVISION, trackId=IDENT,
    rightsConfirmed=dict(b('선택한 제목과 링크를 공유할 권리 확인.'), const=True),
    reviewConsent=dict(b('선택한 제목과 링크의 운영 검토 요청.'), const=True)), '본인 보관함에서 선택한 링크 한 개.')
for method in ('get', 'post'):
    NATIVE.add((method, SAVED_MUSIC))
    OPS[(method, SAVED_MUSIC)] = entry('여행', '여행 플레이리스트 ' + ('조회' if method == 'get' else '추가'),
        READ if method == 'get' else BROWSER, '준비 중 또는 진행 중인 여행의 현재 수락 멤버가 이용합니다.',
        ('현재 가입·차단·원본·검토 상태를 확인합니다. DJ 역할이나 전체 음악 공유 설정을 변경하지 않습니다.' if method == 'get' else
         '본인 보관함의 곡 한 개를 여행 목록 끝에 추가하고 운영 검토를 요청합니다. 같은 곡을 다시 보내면 새 항목 없이 현재 목록을 반환합니다. '
         '여행 목록은 200곡까지이며 넘으면 409 Room playlist limit reached; delete a track first, 원본 목록 revision이 다르거나 곡이 없으면 409 Music list changed; choose it again입니다.'),
        '차량 조회에는 rooms:read, 추가에는 rooms:interact와 현재 functionalRevision, 개인 보관함의 playlists:read(없으면 403 SCOPE_DENIED)도 필요합니다. '
        '종료·취소 여행은 409 TRIP_STATE_CONFLICT, 비멤버는 404. 원본 목록 revision 충돌 시 본인 목록을 다시 읽습니다.',
        {'200': response(SAVED_MUSIC_LIST, '현재 참여자가 볼 수 있는 여행 플레이리스트.')},
        ['400', '401', '403', '404', '409', '413', '429', '503'])
OPS[('post', SAVED_MUSIC)]['example'] = dict(playlistId='a'*32, playlistRevision=1, trackId='b'*32,
                                            rightsConfirmed=True, reviewConsent=True)
BODY[('patch', SAVED_MUSIC_POSITION)] = strict(dict(afterId=nullable(dict(IDENT, description='이 항목 바로 뒤에 둘 보이는 항목 ID. null이면 맨 앞입니다.'))),
    '보이는 항목 한 개의 새 위치.')
NATIVE.add(('patch', SAVED_MUSIC_POSITION))
OPS[('patch', SAVED_MUSIC_POSITION)] = entry('여행', '여행 플레이리스트 순서 변경', BROWSER,
    '준비 중 또는 진행 중인 여행의 현재 DJ나 여행 소유자가 이용합니다.',
    '보이는 항목을 다른 보이는 항목 바로 뒤나 맨 앞으로 옮깁니다. 다른 항목의 공개·검토 상태는 바꾸지 않고 여행 음악 변경을 알립니다.',
    '차량은 rooms:interact와 현재 functionalRevision이 필요하며 정차 화면에서만 호출합니다. 403 Only the DJ or trip owner may reorder trip music은 DJ·소유자가 아닌 경우, '
    '400 Invalid playlist order는 잘못된 ID나 자기 자신 뒤, 409 Music list changed; reload before reordering은 항목이 사라졌거나 보이지 않게 된 경우이며 목록을 다시 읽습니다. 같은 요청을 재전송해도 같은 순서가 됩니다.',
    {'200': response(SAVED_MUSIC_LIST, '바뀐 순서의 여행 플레이리스트.')},
    ['400', '401', '403', '404', '409', '413', '429', '503'])
OPS[('patch', SAVED_MUSIC_POSITION)]['example'] = dict(afterId=None)
BODY[('put', NOW_PLAYING)] = strict(dict(itemId=IDENT), '차량에서 연 보이는 여행 플레이리스트 항목.')
NATIVE.add(('put', NOW_PLAYING))
OPS[('put', NOW_PLAYING)] = entry('여행', '차량 재생 곡 기록', NATIVE_AUTH,
    '진행 중 또는 준비 중인 여행의 수락 멤버가 차량에서 항목을 열 때 호출합니다.',
    '본인 멤버 기록의 최근 재생 항목만 바꾸고 여행 음악 변경을 알립니다. 외부 음악 앱을 재생·제어하지 않습니다.',
    '차량 전용이며 브라우저 호출은 403 Play trip music from the vehicle입니다. rooms:interact와 현재 functionalRevision이 필요하고 계정별 분당 60회로 제한합니다. '
    '409 Music list changed; reload before playing은 항목이 사라졌거나 보이지 않게 된 경우입니다. 재전송하면 시각만 갱신됩니다.',
    {'200': response(SAVED_MUSIC_LIST, '재생 기록이 반영된 여행 플레이리스트.')},
    ['400', '401', '403', '404', '409', '413', '429', '503'])
OPS[('put', NOW_PLAYING)]['example'] = dict(itemId='a'*32)

NATIVE_VOICE_PARTICIPATION = '/v1/native/trips/{id}/voice-participation'
BODY[('patch', NATIVE_VOICE_PARTICIPATION)] = strict({
    **deepcopy(BODY[('patch', T + '/voice-participation')]['properties']),
    'functionalRevision': n('현재 연결의 기능 설정 변경 번호.', minimum=1, maximum=2147483647)},
    '같은 계정·여행의 참여 한 항목만 변경합니다. 현재 인증서·기기·가입 문맥을 재검증합니다.')
for method in ('get', 'patch'):
    OPS[(method, NATIVE_VOICE_PARTICIPATION)] = entry('여행',
        '차량에서 내 여행 워키토키 참여 ' + ('조회' if method == 'get' else '변경'), NATIVE_AUTH,
        '현재 계정이 수락한 진행 중 여행 ID를 사용합니다.',
        OPS[(method, T + '/voice-participation')]['effects'],
        '기기 인증과 rooms:read, 쓰기에는 rooms:interact 및 functionalRevision이 필요합니다. '
        '브라우저 호출은 거부합니다. 마이크 권한은 Android에서 별도로 확인하며 자동 녹음하지 않습니다. private, no-store.',
        {'200': response(VOICE_PARTICIPATION, '웹과 같은 계정·여행 참여 설정.')},
        ['400', '401', '403', '404', '409', '413', '429', '503'])

LISTEN_TOGETHER = '/v1/native/trips/{trip}/listen-together'
FUNCTIONAL_REVISION = n('현재 연결의 기능 설정 변경 번호.', minimum=1, maximum=2147483647)
LISTEN_TOGETHER_SESSION = strict(dict(
    id=IDENT,
    revision=n('세션 변경 번호. 준비 차량·상태가 바뀔 때마다 증가합니다.', minimum=1, maximum=2147483647),
    state=s('preparing은 준비 차량 모집, playing은 startAtMs 기준 재생 중, ended는 종료된 결과입니다.',
            enum=['preparing', 'playing', 'ended']),
    deviceCount=n('준비했거나 재생에 참여 중인 차량 수.', minimum=0),
    joined=b('요청한 이 기기(같은 계정·기기·grant)가 준비 또는 참여 중인지.'),
    startAtMs=nullable(n('서버 Unix 밀리초 기준 공동 시작 시각. 준비 중에는 null.', minimum=0)),
    endedReason=nullable(s('host-ended(방장 종료), track-finished(곡 종료), everyone-left(모두 나감), trip-closed(여행 종료).',
                           enum=['host-ended', 'track-finished', 'everyone-left', 'trip-closed']))),
    '여행당 하나뿐인 함께 듣기 세션.')
LISTEN_TOGETHER_STATE = strict(dict(
    tripId=IDENT,
    available=b('서버가 허용한 시연 여행인지. false이면 session은 null이고 쓰기는 403입니다.'),
    serverTimeMs=n('응답을 만든 서버 Unix 밀리초. 차량은 왕복시간을 반영해 단조 시계에 대응시킵니다.', minimum=0),
    host=b('요청자가 방장인지. 방장만 함께 재생·모두 종료를 할 수 있습니다.'),
    minimumDevices=n('함께 재생에 필요한 준비 차량 수(방장 포함).', const=2),
    track=strict(dict(id=s('팀 소유 시연 음원 ID.', enum=['wegoh-demo-01']), version=n('음원 버전.', const=1),
                      sha256=s('차량에 포함된 WAV 파일의 SHA-256.', pattern='^[a-f0-9]{64}$'),
                      durationMs=n('음원 길이(밀리초).', minimum=1)), '모든 차량이 같은 파일인지 확인하는 기준.'),
    session=nullable(LISTEN_TOGETHER_SESSION)), '함께 듣기 제어 상태. 서버는 음원을 저장·중계하지 않습니다.')
BODY[('put', LISTEN_TOGETHER + '/participation')] = strict(dict(
    sessionId=nullable(IDENT), trackSha256=s('이 기기에 있는 음원의 SHA-256.', pattern='^[a-f0-9]{64}$'),
    joined=b('true는 참여 준비 또는 재생 중 세션 참여, false는 이 기기만 나가기.'),
    functionalRevision=FUNCTIONAL_REVISION),
    '사용자가 화면에서 명시적으로 누른 참여·나가기 한 번. sessionId가 null이면 현재 세션에 들어가거나 새로 준비합니다.')
BODY[('post', LISTEN_TOGETHER + '/start')] = strict(dict(sessionId=IDENT,
    revision=LISTEN_TOGETHER_SESSION['properties']['revision'], functionalRevision=FUNCTIONAL_REVISION),
    '방장이 본 준비 상태 그대로 시작합니다. 중간에 준비 차량이 바뀌면 409입니다.')
BODY[('post', LISTEN_TOGETHER + '/end')] = strict(dict(sessionId=IDENT, functionalRevision=FUNCTIONAL_REVISION),
    '방장의 모두 종료.')
for method, suffix, title, effects in (
        ('get', '', '함께 듣기 상태 조회',
         '조회한 기기가 참여 중이면 연결 확인 시각을 갱신합니다. 8초 동안 확인이 없는 기기와 수락 멤버가 아닌 계정은 참여에서 빠지며, '
         '다시 연결돼도 사용자가 다시 참여해야 합니다. 곡 길이가 지나면 track-finished로, 재생 중 모두 빠지면 everyone-left로 끝나고 종료 결과는 60초 동안 보입니다. '
         '시연 여행이 아니면 available=false, session=null입니다.'),
        ('put', '/participation', '함께 듣기 참여 준비·나가기',
         '준비 중에는 준비 차량에, 재생 중에는 현재 위치부터 듣는 참여 차량에 넣거나 이 기기만 뺍니다. 같은 계정의 다른 기기·새 grant는 별도 기기로 봅니다. '
         '준비 중 세션의 마지막 기기가 나가면 세션이 사라집니다. 음원 해시가 다르면 409 LISTEN_TOGETHER_TRACK_MISMATCH, 보낸 sessionId가 현재 세션과 다르면 409 LISTEN_TOGETHER_SESSION_CHANGED입니다.'),
        ('post', '/start', '함께 재생',
         '방장 차량을 포함해 2대 이상 준비되면 준비 차량을 확정하고 서버 기준 4초 뒤를 startAtMs로 정합니다. '
         '이미 재생 중인 같은 세션의 재전송·중복 탭은 기존 세션을 그대로 반환합니다. 방장이 아니면 403 LISTEN_TOGETHER_HOST_REQUIRED, '
         '준비 중 revision이 다르면 409 LISTEN_TOGETHER_SESSION_CHANGED, 끝난 세션은 SESSION_ENDED, 방장 기기가 준비하지 않았으면 HOST_NOT_READY, 2대 미만이면 NOT_ENOUGH_DEVICES입니다.'),
        ('post', '/end', '함께 듣기 모두 종료',
         '세션을 host-ended로 끝내고 참여 차량을 모두 비웁니다. 이미 끝난 세션은 그대로 반환합니다. 종료된 세션은 다시 시작하지 않으며 새 참여는 새 세션을 만듭니다. '
         '방장이 아니면 403 LISTEN_TOGETHER_HOST_REQUIRED, sessionId가 현재 세션과 다르면 409 LISTEN_TOGETHER_SESSION_CHANGED입니다.')):
    OPS[(method, LISTEN_TOGETHER + suffix)] = entry('여행', '차량 ' + title + ' (시연)', NATIVE_AUTH,
        '서버 설정으로 허용한 시연 여행(준비 또는 진행 중)의 현재 수락 멤버가 차량에서 사용합니다. 차량 앱은 정차 중에만 이 화면을 엽니다.',
        effects + ' 변경은 rooms WSS의 music 영역 알림으로 전하고 차량은 이 정본을 다시 읽습니다. 세션은 서버 프로세스 메모리에만 있으며 재시작하면 사라집니다.',
        '기기 인증과 rooms:read, 쓰기에는 rooms:interact 및 functionalRevision이 필요합니다. 차량 기기가 아닌 호출은 404 LISTEN_TOGETHER_UNAVAILABLE, '
        '비멤버·pending은 404 Trip unavailable, 종료·취소 여행은 409 TRIP_STATE_CONFLICT, 수락 멤버가 아니면 403 LISTEN_TOGETHER_MEMBERSHIP_REQUIRED, '
        '시연 여행이 아닌 쓰기는 403 LISTEN_TOGETHER_NOT_ENABLED입니다. 쿼리·필드·형식 오류는 400 LISTEN_TOGETHER_INVALID_REQUEST, 본문 1 KiB 초과는 413 LISTEN_TOGETHER_REQUEST_TOO_LARGE입니다. '
        '409 LISTEN_TOGETHER_SESSION_CHANGED는 정본을 다시 읽은 뒤 사용자가 다시 누릅니다. private, no-store.',
        {'200': response(LISTEN_TOGETHER_STATE, '요청한 기기 기준 함께 듣기 상태.')},
        ['400', '401', '403', '404', '409', '413', '429', '503'])


def trip_model(schema, **extra):
    fields = deepcopy(schema['properties'])
    if 'roomId' in fields:
        fields.pop('roomId')
        fields['tripId'] = IDENT
    fields.update(extra)
    return strict(fields, '현재 여행과 별도 목적·가입 세대·기한을 검사한 응답. 내부 방 ID는 반환하지 않습니다.')


MODELS = {}
reporting_fields = deepcopy(VEHICLE_MODELS['VehicleRoomReporting']['properties'])
reporting_fields.pop('roomId')
MODELS['TripVehicleReporting'] = strict(reporting_fields, '유한한 기기별 여행 보고·수신 허가.')
snapshot_fields = deepcopy(VEHICLE_MODELS['VehicleSnapshot']['properties'])
snapshot_fields.pop('roomReporting')
MODELS['TripVehicleSnapshot'] = strict(dict(snapshot_fields, tripId=IDENT,
    tripReporting=nullable(ref('TripVehicleReporting'))), '본인 기기만. 별도 목적을 허용하지 않으면 보고 내용은 없습니다.')
MODELS['TripVehicleReceiving'] = trip_model(VEHICLE_MODELS['VehicleReceiving'])
MODELS['TripVehicleReports'] = trip_model(VEHICLE_MODELS['VehicleReports'])
MODELS['TripCommandGrant'] = trip_model(COMMAND_MODELS['CommandGrant'])
MODELS['TripCommandMember'] = trip_model(COMMAND_MODELS['CommandMember'])
MODELS['TripDeviceRequest'] = trip_model(COMMAND_MODELS['DeviceRequest'])
MODELS['TripCommandAccess'] = trip_model(COMMAND_MODELS['CommandRoomAccess'],
    grants=arr(ref('TripCommandGrant'), '현재 여행의 허용된 grant.'))
MODELS['TripCommandList'] = trip_model(COMMAND_MODELS['CommandList'], tripId=IDENT,
    requests=arr(ref('TripDeviceRequest'), '현재 허용된 본인 요청.'))
MODELS['TripFriendRemotes'] = TRIP_REMOTES
FEATURE_OPS = {'reports': {}, 'commands': {}, 'results': {}}
FEATURE_BODY = {}


def feature_entry(feature, method, path, title, schema, *, body=None, code='200', native=False, effects=None):
    FEATURE_OPS[feature][(method, path)] = entry('여행', title,
        NATIVE_AUTH if native else READ if method == 'get' else BROWSER,
        '현재 여행 ID로 조회하고 본인 목적별 동의와 기기의 현재 권한을 확인합니다.',
        effects or 'accepted 멤버·여행 상태·동의·현재 친구·차단·가입 세대와 하위 ID 소속을 다시 검사합니다. '
        '여행은 자동 만료되지 않지만 목적별 허가는 유한한 기한을 유지합니다. 종료·탈퇴 후 새 실행은 거부하고 본인 철회는 허용합니다.',
        '409는 정본을 다시 읽고 선택합니다. private, no-store. native는 wire의 정확한 경로·목적과 쓰기 본문의 functionalRevision을 검사합니다. '
        '차량 명령의 처리 상태는 명령 조회 결과에서 확인합니다.',
        {code: response(schema, '현재 목적별 허가를 통과한 viewer 기준 응답.')},
        # 410 is the native credential's GRANT_EXPIRED; browser routes have no 410.
        ['400', '401', '403', '404', '409'] + (['410'] if native else []) + ['413', '429', '503'])
    if body is not None:
        FEATURE_BODY[(method, path)] = deepcopy(body)
        period = FEATURE_BODY[(method, path)].get('properties', {}).get('expiresInHours')
        if period:
            period['description'] = '명시 목적 기한. 현재 기기와 목적별 상한을 넘지 않으며 여행 상태는 별도로 검사합니다.'


VT = '/v1/social/trips/{trip}'
VN = '/v1/native/trips/{trip}'
OLD_ROOM = '/v1/social/rooms/{room}'
REVOKED = strict({'tripId': IDENT, 'status': s('revoked', enum=['revoked'])}, '본인 여행 보고 허가 철회.')
coordinates = dict(latitude=dict(type='number', minimum=-90, maximum=90, description='관측한 위도.'),
                   longitude=dict(type='number', minimum=-180, maximum=180, description='관측한 경도.'),
                   accuracyMeters=nullable(dict(type='number', minimum=0, maximum=10000, description='기기가 보고한 수평 오차(m).')),
                   capturedAt=TIME)
current_locations = strict(dict(tripId=IDENT, serverNow=TIME, shareId=nullable(IDENT),
    locations=arr(strict(dict(coordinates, accountId=ACCOUNT, name=s('일행의 등록 이름.'),
        source=s('관측 기기.', enum=['phone','vehicle'])), '이 일행의 가장 최근 관측 한 건.'), '현재 볼 수 있는 일행의 위치.'),
    cars=arr(strict(dict(coordinates, carId=IDENT, source=s('관측 기기.', enum=['phone','vehicle'])),
        '운전자·동승자 중 locations에 나온 가장 최근 관측 한 건을 이 차의 현재 위치로 씁니다.'),
        '현재 위치를 볼 수 있는 여행 차. 차 순번 순서이며 내 차도 포함합니다. 경로·픽업·드랍 정보는 포함하지 않습니다.')),
    '공유를 켠 본인에게만 현재 공유 구간의 shareId를 제공합니다.')
for root, native in ((VT, False), (VN, True)):
    feature_entry('reports', 'get', root + '/locations', '여행 일행의 현재 위치 확인', current_locations, native=native,
        effects='진행 중인 여행의 참여자는 자기 위치를 공유하지 않아도 일행이 공유한 60초 이내 위치를 봅니다. 차단된 상대의 위치와 과거 위치는 제외합니다. '
        '차 위치는 같은 규칙을 통과한 운전자·동승자 위치에서만 만들며, 운전자가 차단 관계인 차는 제외합니다.')
    feature_entry('reports', 'post', root + '/locations/me', '이 여행에 내 현재 위치 보내기',
        strict(dict(status=s('위치 반영 결과.', enum=['accepted'])), '최근 위치 하나를 저장합니다.'), native=native,
        body=strict(dict(coordinates, shareId=IDENT), '위치 공유를 켤 때 발급된 이 여행의 현재 shareId와 본인 기기의 관측값.'),
        effects='본인의 명시적 공유 동의와 현재 가입·공유 구간을 다시 확인하고 암호화한 최신 좌표 하나만 갱신합니다. '
        '차량 요청은 현재 기기·연결에 결합하고 연결 해제 후 관측을 숨깁니다. 철회·탈퇴·여행 종료 시 최신 관측을 삭제합니다.')
feature_entry('reports', 'get', '/v1/devices/{device}/trips/{trip}/vehicle-domain', '기기의 여행 보고 설정', ref('TripVehicleSnapshot'))
feature_entry('reports', 'get', VN + '/vehicle-domain', '현재 기기의 여행 보고 설정', ref('TripVehicleSnapshot'), native=True)
feature_entry('reports', 'put', VT + '/device-reporting', '기기의 여행 보고·수신 허가', ref('TripVehicleSnapshot'), body=VEHICLE_BODY[('put', OLD_ROOM + '/device-reporting')])
feature_entry('reports', 'delete', VT + '/device-reporting', '내 여행의 기기 보고 허가 철회', REVOKED)
for method in ('get', 'put'):
    feature_entry('reports', method, VT + '/report-receiving', '내 웹의 여행 보고 수신', ref('TripVehicleReceiving'),
        body=VEHICLE_BODY[('put', OLD_ROOM + '/report-receiving')] if method == 'put' else None)
feature_entry('reports', 'delete', VT + '/report-receiving', '내 웹의 여행 보고 수신 철회', REVOKED)
for root, native in ((VT, False), (VN, True)):
    feature_entry('reports', 'get', root + '/device-reports', '현재 일행이 공유한 차량 위치와 친구의 방문 보고',
        ref('TripVehicleReports'), native=native, effects='차단 관계를 제외한 현재 여행의 멤버는 자신의 위치 공유 선택과 무관하게 일행이 이 여행에 공유한 최근 차량 위치를 읽습니다. '
        '방문 보고만 기존 친구 관계, 양쪽의 송수신 조건과 차량 수신 권한을 확인합니다.')
for kind in ('location', 'visits'):
    payload = deepcopy(VEHICLE_BODY[('post', '/v1/native/rooms/{room}/reports/' + kind)])
    payload['properties']['reportingRevision'] = payload['properties'].pop('roomRevision')
    payload['required'] = ['reportingRevision' if key == 'roomRevision' else key for key in payload['required']]
    feature_entry('reports', 'post', VN + '/reports/' + kind, '기기의 여행 ' + kind + ' 보고', ref('VehicleReceipt'), body=payload, native=True)

CT = '/v1/social/trips/{room}'
for method, suffix, title, model, code in (
        ('get', '/device-command-access', '여행 명령 참여와 허가 조회', 'TripCommandAccess', '200'),
        ('put', '/device-command-access', '내 여행 명령 참여 설정', 'TripCommandMember', '200'),
        ('put', '/device-command-grants/{device}/{peer}', '여행에서 본인 기기 명령 허가', 'TripCommandGrant', '200'),
        ('delete', '/device-command-grants/{device}/{peer}', '여행에서 본인 기기 명령 허가 철회', 'CommandWithdrawal', '200'),
        ('post', '/device-requests', '여행에서 기기 명령 요청', 'TripDeviceRequest', '201'),
        ('get', '/device-requests', '여행에서 내 명령 상태', 'TripCommandList', '200'),
        ('delete', '/device-requests/{identifier}', '여행 명령 취소', 'CommandCancellation', '200')):
    feature_entry('commands', method, CT + suffix, title, ref(model), code=code,
        body=COMMAND_BODY.get((method, OLD_ROOM + suffix)))
feature_entry('commands', 'delete', CT + '/device-command-access', '내 여행 명령 참여 철회',
    strict({'tripId': IDENT, 'status': s('withdrawn', enum=['withdrawn'])}, '탈퇴·종료 뒤에도 본인 철회.'))
feature_entry('commands', 'delete', OLD_ROOM + '/device-command-access', '기존 방 명령 참여 철회',
    strict({'status': s('withdrawn', enum=['withdrawn'])}, 'linked 방은 구형 경로에서 거부.'))
REMOTE_DEVICE = strict({'id': IDENT, 'name': s('연결한 차량 이름.'),
    'receiveEnabled': {'const': True, 'description': '명령을 받을 수 있는 차량만 반환합니다.'}}, '차주가 이번 여행에 선택할 수 있는 차량.')
feature_entry('commands', 'get', T + '/cars/{carId}/remote-devices', '이 여행 리모컨에 쓸 내 차량 목록',
    strict({'devices': arr(REMOTE_DEVICE, '선택 가능한 차량.')}, '이 여행의 리모컨 승인 후보.'),
    effects='준비 중 또는 진행 중인 여행에서 해당 차의 운전자만 자신이 연결한 차량을 조회합니다. 명령 수신이 켜진 차량만 표시합니다.')
feature_entry('commands', 'get', VT + '/vehicle-remotes', '이번 여행의 내 리모컨', ref('TripFriendRemotes'),
    effects='여행이 진행 중이고 탑승 배정·차주 사전 허용·친구 관계·차량 수신이 유효한 경우 선택된 차량만 반환합니다.')
feature_entry('commands', 'post', VT + '/vehicle-remotes/{device}/commands', '여행에서 친구 차량 조작 요청',
    ref('TripDeviceRequest'), code='201', body=TRIP_REMOTE_COMMAND,
    effects='현재 여행 차주가 정책으로 미리 허용한 차량 한 대와 조작만 접수합니다. 하차·철회·여행 종료 시 새 명령과 남은 명령 처리가 중단됩니다. '
    '운전석(' + DRIVER_AREA + ') 좌석·창문을 대상으로 한 인자는 400 Invalid control value로 거절합니다. 유효한 known 지원 힌트의 미지원 조작·위치·값은 각각 422 VEHICLE_CONTROL_UNSUPPORTED, '
    'VEHICLE_CONTROL_AREA_UNSUPPORTED, VEHICLE_CONTROL_VALUE_UNSUPPORTED로 거절합니다. 힌트가 없거나 오래되면 기존 입력 계약을 유지하고 차량이 SDK를 다시 검사합니다. '
    '같은 여행·조작·좌석/창문의 대기 명령은 superseded로 바꾸고 새 명령은 최대 30초 안에 만료됩니다. 차량이 주행 중이라 실행하지 않으면 명령 조회의 reason이 driving-restricted입니다. '
    '허용 정책·탑승 배정이 없으면 403, grantRevision이 다르거나 같은 eventId에 다른 본문이면 409, 요청자별 1000건 상한은 409 Control history limit reached입니다.')
_command = FEATURE_OPS['commands'][('post', VT + '/vehicle-remotes/{device}/commands')]
_command['errors'] = [*_command['errors'][:6], '422', *_command['errors'][6:]]
_command['errorDescriptions'] = {'422': '선택한 차량이 현재 보고한 지원 범위에 없는 조작·위치·값입니다(VEHICLE_CONTROL_UNSUPPORTED, VEHICLE_CONTROL_AREA_UNSUPPORTED, VEHICLE_CONTROL_VALUE_UNSUPPORTED). 같은 요청을 반복하지 말고 지원 범위를 다시 읽습니다.'}

HISTORY_REF = strict({'id': IDENT, 'revision': REVISION, 'permissionRevision': REVISION}, '이미 저장한 본인 기록. 중복 요청은 같은 ID.')
PERIOD = strict({'startedAt': TIME, 'endedAt': nullable(TIME)}, '확인 가능한 본인 참여 기간만.')
UNAVAILABLE = strict({'id': IDENT, 'state': s('unavailable', enum=['unavailable'])}, '현재 권한으로 공개할 수 없는 참조.')
MISSION_RESULT = strict({'id': IDENT, 'state': s('현재 공개 가능한 미션 상태.'), 'course': ref('MissionCourse'),
    'participants': arr(strict({'accountId': ACCOUNT, 'name': s('현재 표시 이름.'), 'completedCheckpoints': n('수동 확인 수.', minimum=0, maximum=3)}, '보이는 참여자.'), '현재 참여 동의와 차단을 검사.'),
    'completedAt': nullable(TIME), 'confirmationSource': s('user-confirmed', enum=['user-confirmed']),
    'physicalArrivalVerified': {'const': False, 'description': '실제 도착 측정 아님.'}, 'safety': ref('MissionSafety')}, '현재 권한 기준 미션 결과.')
AGREED_PLACE = strict({'id': IDENT, 'kind': s('agreed', enum=['agreed']), 'accountId': ACCOUNT, 'place': PLACE}, '종료 당시 합의한 장소 후보. 방문 측정 아님.')
SELECTED_PLACE = strict(dict(PROPOSAL['properties'], kind=s('selected', enum=['selected'])), '일정에 선택한 장소.')
SUMMARY = strict({'title': s('현재 검토가 허용하는 여행 제목.'), 'startedAt': TIME, 'endedAt': TIME,
    'members': arr(strict({'accountId': ACCOUNT, 'role': ROLE, 'name': s('현재 이름.')}, '종료 당시 역할과 현재 가시성.'), '현재 상태 공유와 가입 세대가 일치한 멤버.'),
    'cars': arr(strict(dict(CAR_FIELDS, id=IDENT, driverId=ACCOUNT, riders=arr(ACCOUNT, '보이는 탑승자.')), '종료 당시 차 배정.'), '현재 보이는 운전자만.'),
    'courses': arr(strict({'id': s('원 코스 ID.'), 'version': n('종료 당시 버전.', minimum=1), 'title': s('현재 검토된 제목.'), 'addedBy': ACCOUNT}, '원 코스 참조.'), '현재 승인·멤버·차단 확인.'),
    'missions': arr({'anyOf': [MISSION_RESULT, UNAVAILABLE]}, '종료 당시 참조에 현재 공개 조건 적용.'),
    'places': arr({'anyOf': [SELECTED_PLACE, AGREED_PLACE, UNAVAILABLE]}, '현재 위치 동의·차단·가입 세대를 다시 확인.'),
    'safety': ref('MissionSafety')}, '자동 기록·임의 점수·속도·원시 음성을 포함하지 않는 공동 요약.')
ARCHIVE_FIELDS = {'tripId': IDENT, 'state': s('종료·취소 또는 과거 탈퇴 상태.', enum=['completed', 'cancelled', 'left']),
    'ownPeriod': PERIOD, 'history': nullable(HISTORY_REF), 'sourceKind': s('이전 출처.', enum=['trip', 'legacy_room'])}
ARCHIVE = dict(strict(dict(ARCHIVE_FIELDS, readOnly=b('항상 읽기 전용.'), startTimeEstimated=b('이전 방 생성 시각을 시작으로 사용했는지.'),
    summary=nullable(SUMMARY), revision=REVISION, summaryState=s('결과 존재 여부.', enum=['available', 'unavailable'])), '종료 후 조회. 탈퇴자는 본인 기간·원기록만.'),
    required=[*ARCHIVE_FIELDS, 'readOnly', 'startTimeEstimated', 'summary'])
for path in (VT + '/archive', VT + '/results'):
    feature_entry('results', 'get', path, '여행 종료 결과와 내 기록', ARCHIVE,
        effects='live 접근을 요구하지 않습니다. 과거 참여와 현재 공개·차단·가입 세대를 재검사합니다. 탈퇴자는 공동 요약을 받지 않습니다.')
feature_entry('results', 'get', '/v1/social/trip-archives', '지난 여행·탈퇴 이력 목록',
    strict({'archives': arr(strict(ARCHIVE_FIELDS, '본인 지난 여행.'), '페이지당 최대 50개.'), 'nextCursor': nullable(IDENT)}, '목록 숨김 여행은 제외.'))
feature_entry('results', 'post', VT + '/history', '여행에서 내 기록 저장', HISTORY_REF, code='201',
    body=strict({'title': s('내 기록 제목.', minLength=1, maxLength=100)}, '2048바이트. 자동 저장하지 않으며 본인이 명시 저장.'),
    effects='여행·계정별 기존 기록 연결을 재사용합니다. 최초 201, 이미 저장했으면 같은 ID로 200. 개인 원기록을 보존합니다.')
FEATURE_OPS['results'][('post', VT + '/history')]['responses']['200'] = response(HISTORY_REF, '이미 저장된 본인 기록.')
BODY.update(FEATURE_BODY)
