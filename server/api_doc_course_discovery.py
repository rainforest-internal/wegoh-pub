from api_doc_shared import ACCOUNT, CHECK, TIME, arr, b, entry, n, nullable, ok, ref, s
from api_doc_trips import strict


TAGS = dict(arr(s('NFC 태그. 최대24자.', maxLength=24), '대소문자 중복 없는 태그.'), maxItems=8)
SUMMARY = strict(dict(id=s('코스 ID.'), version=n('정확한 게시 버전.', minimum=1), title=s('코스 제목.'), author=s('서버 게시자 이름.'),
    description=s('설명.'), stopCount=n('장소 수.', minimum=1, maximum=3),
    stopNames=dict(arr(s('장소 이름. 최대80자.', maxLength=80), '게시 원본의 장소 이름을 방문 순서대로. 개수는 stopCount와 같고 마지막이 목적지.'), minItems=1, maxItems=3), starred=b('본인 별표.'), starCount=n('해당 버전 실제 별표 수.', minimum=0),
    tags=TAGS, canFollow=b('현재 구독 가능한 제작자인지.'), followId=nullable(s('내 제작자 구독 UUID.')), creatorRank=nullable(n('별표 기반 현재 제작자1~3위.', minimum=1, maximum=3)),
    creatorId=nullable(ACCOUNT), hasCover=b('저장된 대표 이미지 존재 여부.'), checksum=CHECK), '현재 사후 제한·계정·차단을 확인한 실제 코스 요약.')
NEWS = strict(dict(SUMMARY['properties'], eventId=s('기존 발행 이벤트 정수의 문자열.'), approvedAt=TIME, read=b('현재 계정이 읽었는지.')), '구독 이후 발행 소식. 중복 구독 경로는 합침.')
LIBRARY = strict(dict(public=arr(SUMMARY, '코스별 최신 가용 버전 중 iPhone에서 숨긴 코스를 빼고 q검색·AND태그로 거른 비위치 인기 카탈로그. 별표 수 내림차순, 제작자 순위, 코스 ID 순. 최대1000.'), saved=arr(SUMMARY, '내 별표 게시 버전. 최대1000.'),
    news=arr(NEWS, '구독한 제작자 또는 구독한 태그의 코스 중 구독 시점 이후 발행되고 현재 볼 수 있는 최근30개.'), following=arr(strict(dict(id=s('내 구독 UUID.'), name=nullable(s('현재 제작자 이름.')), creatorId=nullable(ACCOUNT)), '차단/비활성 제작자는 이름·ID 없음.'), '구독 관리 목록 최대1000.'),
    popularTags=arr(s('대소문자 중복 없는 태그.'), '공개 최신 코스 빈도순 최대1000.'), followedTags=arr(s('구독한 태그.'), '본인 태그 구독 최대1000.'), unreadCount=n('반환된 최근30개 안에서 읽지 않은 수.', minimum=0, maximum=30)), '개인AI·GPS·추정 경로 없는 실데이터 목록.')
DETAIL = strict(dict(pack=ref('DrivePack'), checksum=CHECK, tags=TAGS, hasCover=b('대표 이미지 존재 여부.'), creatorId=nullable(ACCOUNT),
    starred=b('내 별표.'), starCount=n('현재 버전 별표 수.', minimum=0), canFollow=b('현재 제작자 구독 가능.'), followId=nullable(s('내 구독 UUID.'))), '원본 바이트 SHA256을 검증한 공개 코스 상세.')
CREATOR = strict(dict(creator=strict(dict(id=ACCOUNT, name=s('현재 이름.'), courseCount=n('최신 가용 코스 수.', minimum=0), starCount=n('그 코스들의 별표 합.', minimum=0),
    followerCount=n('현재 활성 계정의 실제 구독 수.', minimum=0), following=b('내 구독 여부.'), followId=nullable(s('내 구독 UUID.'))), '이메일·개인 프로필·팔로워 명단 없음.'),
    courses=arr(SUMMARY, '해당 제작자의 최신 가용 코스 최대1000.')), '현재 공개 가능한 제작자 통계.')
BASE = '/v1/native/courses'
OPS = {}
for suffix, title, schema in [('/library', '코스 추천·별표·구독 목록 조회', LIBRARY),
        ('/public/{pack_id}/versions/{version}', '정확한 공개 코스 버전 상세', DETAIL), ('/creators/{creator_id}', '공개 제작자 통계와 코스', CREATOR)]:
    OPS['get', BASE + suffix] = entry('04 코스', title, '현재 개인 mTLS·Bearer와 기존 courses:read scope. 새 기능 목적이나 scope 자동 추가 없음.',
        '차량은 조회·상세·여행 추가만 사용하고 구독/별표/신고/복사는 iPhone에서 관리.',
        '사후 제한·현재 팀 계정·차단·내 저장과 구독을 같은 읽기 경계에서 확인. library는 q검색과 반복 tag AND. 구독 소식은 발행 시점과 현재 공개 상태를 검사.',
        '변경 뒤 다시 조회. 명시 anchor가 필요한 기존 recommendations/query와 다른 비위치 별표 인기 카탈로그이며 개인AI 추천을 가장하지 않음.',
        ok(schema), ['400', '401', '403', '404', '410', '429', '503'])
    OPS['get', BASE + suffix]['errorDescriptions'] = {
        '400': 'library는 q 1개(최대100자)와 tag 최대8개 외 query를 거절합니다. 상세·제작자 경로는 query를 받지 않습니다. Native 요청에 Origin·Cookie가 있으면 INVALID_REQUEST입니다.',
        '404': '현재 가용하지 않거나 차단·비활성 제작자의 코스, 공개 코스가 없는 제작자, 또는 courses:read 허용목록 밖 경로입니다.',
        '410': 'GRANT_EXPIRED: 현재 개인 grant의 원 연결 기한이 만료됐습니다. 명시 재연결 흐름을 따릅니다.',
        '429': 'Native 호스트 전체 인증 요청 한도(분당600회)를 넘었습니다. Retry-After: 60 이후 다시 조회합니다.'}
ROUTE = strict(dict(distanceMeters=n('총 도로 거리(m).', minimum=0), durationSeconds=n('총 예상 소요 시간(s).', minimum=0),
    path=dict(type='array', maxItems=2000, items=dict(type='array', minItems=2, maxItems=2, items={'type': 'number'}),
        description='지도용 [lat,lng] 도로 경로. 첫 점과 마지막 점을 보존해 축약합니다.')), '저장하지 않는 경로 미리보기.')
OPS['post', BASE + '/{pack_id}/versions/{version}/route-preview'] = entry('04 코스', '차량 코스 도로 경로 미리보기',
    '현재 개인 mTLS·Bearer와 기존 courses:read scope. 새 기능 목적이나 scope 자동 추가 없음.',
    'Content-Type: application/json으로 공개 코스 상세에서 받은 checksum과 그 상세의 장소 좌표 전부(1~3개)를 같은 순서로 points에 보냅니다. query·origin·다른 필드는 받지 않습니다. 서버는 코스 잠금 안에서 현재 공개 상세의 checksum·장소 좌표와 정확히 대조합니다.',
    '카카오모빌리티 자동차 길찾기를 한 번 호출해 거리(m), 시간(s), 최대 2000개 [lat,lng] 도로 좌표만 반환하며 서버 캐시·DB·코스에 저장하지 않습니다. 장소가 하나면 외부 호출 없이 0/0/빈 path입니다. 응답 Cache-Control: private, no-store.',
    '계정당 최근 60초 20회, 프로세스 전체 동시 작업 4개, 전체 4초 제한이며 자동 재시도는 없습니다. 429는 Retry-After: 60 이후 다시 요청합니다. 409는 공개 상세를 다시 읽고 새 checksum·좌표로 요청합니다. 계산 뒤 인증·코스 대조를 다시 해 달라지면 401로 결과를 버립니다.',
    {**ok(ROUTE), '422': {'description': 'ROUTE_NOT_FOUND: 공급자가 경로를 찾지 못했습니다. 마커만 표시합니다.',
        'content': {'application/json': {'schema': ref('ApiError')}}}},
    ['400', '401', '403', '404', '408', '409', '410', '413', '429', '502', '503', '504'],
    example={'checksum': '0' * 64, 'points': [{'lat': 37.544, 'lng': 127.037}, {'lat': 37.55, 'lng': 127.05}]})
OPS['post', BASE + '/{pack_id}/versions/{version}/route-preview']['errorDescriptions'] = {
    '400': 'ROUTE_INPUT_INVALID: JSON 형식·checksum(64 hex)·알 수 없는 필드·좌표 범위·장소 1~3개를 확인하세요. Content-Type이 application/json이 아니면 INVALID_REQUEST입니다.',
    '404': '현재 가용하지 않거나 차단·비활성 제작자의 코스 버전, query가 붙은 요청, 또는 Native 인증이 아닌 요청입니다.',
    '408': 'REQUEST_TIMEOUT: 본문 수신이 5초를 넘었습니다.',
    '409': 'COURSE_ROUTE_CHANGED: checksum 또는 points가 현재 공개 상세의 장소 좌표와 다릅니다. 상세를 다시 조회하세요.',
    '410': 'GRANT_EXPIRED: 현재 개인 grant의 원 연결 기한이 만료됐습니다. 명시 재연결 흐름을 따릅니다.',
    '413': 'REQUEST_TOO_LARGE: 요청 본문이 4096바이트를 넘었습니다.',
    '429': 'ROUTE_RATE_LIMITED: 계정당 최근 60초 20회 초과. Retry-After: 60. Native 호스트 전체 인증 한도 초과도 429입니다.',
    '502': 'ROUTE_PROVIDER_UNAVAILABLE: 외부 인증·쿼터·리다이렉트·응답 오류. 외부 본문이나 키는 반환하지 않습니다.',
    '503': 'ROUTE_UNAVAILABLE: 경로 키 파일이 없습니다. ROUTE_BUSY: 전체 동시 작업 4개가 실행 중입니다. 코스 저장소를 읽지 못해도 503입니다.',
    '504': 'ROUTE_TIMEOUT: 전체 4초 제한을 넘었습니다. 늦은 결과를 버립니다.'}
POINT = dict(type='object', additionalProperties=False, required=['lat', 'lng'], properties={
    'lat': dict(type='number', minimum=32, maximum=39, description='공개 상세 장소의 위도. 대한민국 범위.'),
    'lng': dict(type='number', minimum=124, maximum=132, description='공개 상세 장소의 경도. 대한민국 범위.')},
    description='공개 상세의 장소 좌표를 그대로 보낸 값.')
BODY = {('post', BASE + '/{pack_id}/versions/{version}/route-preview'): dict(type='object', additionalProperties=False,
    required=['checksum', 'points'], description='공개 상세와 정확히 같은 checksum과 장소 좌표. 출발지(origin)는 받지 않습니다.', properties={
        'checksum': dict(type='string', pattern='^[a-f0-9]{64}$', description='공개 상세 응답의 checksum.'),
        'points': dict(type='array', minItems=1, maxItems=3, items=POINT, description='공개 상세 pack.stops의 좌표 전부를 방문 순서대로.')})}
