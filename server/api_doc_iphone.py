"""iPhone app contracts (/v1/iphone/*, /iphone-login); documentation only, never grants access.

The iPhone routes are registered with include_in_schema=False because they live on a
separate hostname with their own browser-approved Bearer session. This module adds their
operations to the final document. Where an iPhone route shares a handler with a documented
browser or vehicle route, only that operation's success schema (and plain request schema)
is reused from the generated document; authentication, parameters, iPhone body rules and
error codes are authored here from the iPhone branch of each handler.
"""
import copy
import re

from api_doc_models import obj, s, n, b, arr, ref, nullable, IDENT, ACCOUNT

METHODS = ('get', 'post', 'put', 'patch', 'delete')
SECURITY = 'IPhoneSession'
SESSION_SECONDS = 604800
SCOPES = {
    'account:read': '내 프로필·세션 확인, 음악 링크 목록 읽기, 푸시 알림 기기 등록',
    'account:write': '프로필 이름·핸들·차량 프로필 수정, 음악 링크 목록 만들기·수정·삭제',
    'maps:read': '장소 검색, 자동차 경로 미리보기, 손들기 주변 후보 조회',
    'vehicles:manage': '차량 연결 코드 확인·허용·취소, 연결 차량 목록·해제, 차량 기능 공유 설정',
    'courses:read': '내 코스·공개 코스 라이브러리·제작자 조회',
    'courses:write': '코스 게시·복사, 별표·구독·태그 구독·숨김·소식 읽음·신고',
    'friends:read': '친구 목록·검색·친구 프로필 읽기',
    'friends:manage': '친구 요청·수락·거절·연결 해제·차단',
    'trips:read': '여행 목록·상세·위치·음악·음성 수신·결과 읽기',
    'trips:manage': '여행 만들기·초대·참여·차·탑승·장소·코스·시작/종료·손들기·음악·음성 송신',
}
TAGS = {
    'iPhone 01 로그인·세션': '웹에서 승인한 7일 iPhone 세션. 차량 기기 token·웹 쿠키와 별개이며 scope는 로그인 당시 동의로 고정됩니다.',
    'iPhone 02 계정·알림': '본인 프로필 이름·친구 핸들과 세션에 묶인 APNs 알림 기기 등록.',
    'iPhone 03 차량 연결': '차량 화면의 8자 코드를 iPhone에서 확인·허용·취소하고 연결 차량·차량 프로필·기능 공유를 관리합니다.',
    'iPhone 04 친구': '핸들 정확 일치 검색, 요청·수락·거절·해제·차단과 친구 프로필.',
    'iPhone 05 코스·지도': '장소 검색·경로 미리보기, 내 코스 게시·복사, 공개 라이브러리 별표·구독·숨김·신고.',
    'iPhone 06 여행 준비': '여행 만들기·편집·초대·응답, 차·탑승·코스·픽업/드랍 장소와 차량 리모컨 허용 설정.',
    'iPhone 07 여행 진행': '시작·종료·취소, 역할·위치 공유·음성 참여, 손들기와 실시간 위치, 운전 점수.',
    'iPhone 08 차량 리모컨': '진행 중인 여행에서 운전자가 허용한 동승자 리모컨. 운전석은 제외됩니다.',
    'iPhone 09 음악·음성': '내 음악 링크, 여행 음악 단일 목록·함께 듣기 공유, 음성 필터·신고·음성 메시지.',
    'iPhone 10 여행 기록': '종료한 여행의 결과·본인 기록 저장과 공유 장소로 코스 초안 만들기.',
}

ID32 = dict(IDENT)
EPOCH = n('Unix epoch 초.', minimum=0)
EMPTY = {'const': {}, 'description': '업무 필드가 없습니다. iPhone은 Content-Type: application/json과 빈 객체 {}를 보냅니다. 빈 본문은 400입니다.'}
EMPTY_OPTIONAL = {'const': {}, 'description': '업무 필드가 없습니다. Content-Type: application/json으로 빈 본문 또는 빈 객체 {}를 보냅니다.'}
PERSON = obj({'id': ACCOUNT, 'name': s('현재 계정 표시 이름.')}, '현재 활성 계정.')
CARD_STOPS = arr(obj({'id': s('코스 안의 장소 ID.'), 'name': s('장소 이름.'),
                      'lat': {'type': 'number', 'description': '위도.'}, 'lng': {'type': 'number', 'description': '경도.'}},
                     '코스 카드 지도에 그릴 장소.'), 'iPhone 코스 카드 지도용 장소 목록. 상세 조회 없이 카드를 그립니다.')

PARAMS = {
    'peer': ('친구 목록에서 고른 상대의 team- 계정 ID.', ACCOUNT),
    'target': ('대상 계정의 team- 계정 ID. 친구 요청 ID나 기기 ID가 아닙니다.', ACCOUNT),
    'accountId': ('여행 멤버의 team- 계정 ID.', ACCOUNT),
    'speaker': ('현재 여행 음성 발화자의 team- 계정 ID. 본인은 지정할 수 없습니다.', ACCOUNT),
    'creator_id': ('공개 코스 제작자의 team- 계정 ID.', ACCOUNT),
    'device': ('GET /v1/iphone/vehicles에서 받은 본인 연결 차량의 32hex deviceId.', ID32),
    'device_id': ('GET /v1/iphone/vehicles에서 받은 본인 연결 차량의 32hex deviceId.', ID32),
    'user_code': ('차량 화면에 표시된 8자 비교 코드. 혼동 문자(I·O·0·1)는 쓰지 않습니다.',
                  s('8자 비교 코드.', pattern='^[A-HJ-NP-Z2-9]{8}$')),
    'id': ('내 여행 목록 또는 생성 응답의 32hex 여행 ID.', ID32),
    'trip': ('내 여행 목록의 32hex 여행 ID. 내부 방 ID가 아닙니다.', ID32),
    'room': ('내 여행 목록의 32hex 여행 ID. 이 경로는 내부 방 ID를 받지 않습니다.', ID32),
    'carId': ('여행 상세 cars[]의 32hex 차 ID.', ID32),
    'placeId': ('차 장소 목록의 32hex 장소 ID.', ID32),
    'inviteId': ('여행 상세에서 받은 32hex 탑승 초대 ID.', ID32),
    'signal': ('손들기 목록 또는 생성 응답의 32hex 신호 ID.', ID32),
    'identifier': ('음성 메시지 목록의 32hex 메시지 ID.', ID32),
    'item': ('여행 음악 목록 items[]의 32hex 항목 ID.', ID32),
    'playlist_id': ('내 음악 링크 목록의 32hex ID.', ID32),
    'packId': ('여행에 첨부한 코스 pack ID.', s('코스 pack ID.')),
    'pack_id': ('코스 pack ID.', s('코스 pack ID.')),
    'version': ('코스 게시 버전. 1 이상 정수입니다.', n('코스 버전.', minimum=1, maximum=2147483647)),
    'event_id': ('라이브러리 news[]의 소식 eventId.', n('소식 ID.', minimum=1)),
    'follow_id': ('제작자 구독 응답의 followId(UUID).', s('구독 ID.', format='uuid')),
    'tag': ('구독할 코스 태그. NFC 정규화 후 24자 이하이며 대소문자를 구분하지 않습니다.', s('코스 태그.', maxLength=24)),
}

SESSION_401 = ('IPHONE_SESSION_REQUIRED·IPHONE_SESSION_REVOKED·IPHONE_SESSION_EXPIRED입니다. Bearer가 없거나 형식이 다르거나, '
               '로그아웃·웹 일괄 해제·7일 만료·계정 비활성으로 세션이 끝났습니다.')
ERRORS = {
    '400': 'IPHONE_INVALID_REQUEST 또는 handler 입력 검증 오류입니다. Cookie·Origin 헤더, 허용하지 않은 query, Content-Type·JSON·필드 조합이 맞지 않습니다. 같은 요청을 반복하지 말고 본문을 고칩니다.',
    '401': SESSION_401 + ' 저장한 토큰을 지우고 로그인부터 다시 합니다.',
    '403': 'IPHONE_SCOPE_DENIED 또는 이 리소스에 필요한 역할·권한·공유 동의가 없습니다. scope는 로그인 당시 동의 버전으로 고정되므로 새 scope가 필요하면 다시 로그인합니다.',
    '404': 'IPHONE_ROUTE_NOT_FOUND(전용 iPhone 호스트가 아닌 주소)이거나 현재 계정에서 볼 수 없는 리소스입니다. ID를 추측해 순회하지 마세요.',
    '408': 'IPHONE_REQUEST_TIMEOUT: 요청 본문을 5초 안에 받지 못했습니다. 저장 여부를 조회로 확인한 뒤 다시 보냅니다.',
    '409': '현재 상태·revision이 바뀌었거나 한도에 닿았습니다. 최신 정본을 다시 읽고 사용자 선택을 확인합니다.',
    '410': '요청 기한이 지났습니다. 처음 단계부터 새로 시작합니다.',
    '413': 'IPHONE_REQUEST_TOO_LARGE 또는 handler 본문 상한 초과입니다. 내용을 잘라 보내지 말고 사용자가 줄이게 합니다.',
    '422': 'FastAPI가 경로의 정수 파라미터 형식을 검증하지 못했습니다. detail의 loc를 확인합니다.',
    '429': '계정 또는 서비스 요청 한도를 넘었습니다. Retry-After(대개 60초)를 따릅니다.',
    '502': '외부 지도·장소 공급자 응답을 읽지 못했습니다. 연결을 확인하고 잠시 후 다시 시도합니다.',
    '503': 'IPHONE_SERVICE_UNAVAILABLE 또는 저장소·무결성 확인 실패입니다. 성공으로 표시하지 말고 이후 조회로 확인합니다.',
}
# Handlers that reuse native_authorization.read_body answer without the IPHONE_ prefix.
NATIVE_BODY = {'408': 'REQUEST_TIMEOUT: 요청 본문을 5초 안에 받지 못했습니다. 저장 여부를 조회로 확인한 뒤 다시 보냅니다.',
               '413': 'REQUEST_TOO_LARGE: 본문이 12288바이트를 넘었습니다. 내용을 잘라 보내지 말고 사용자가 줄이게 합니다.'}
GRANT_EXPIRED = ('GRANT_EXPIRED: 이 차량 연결(grant)의 원 기한이 지났습니다. CONSENT_REVOKED(403)는 철회된 연결입니다. '
                 '차량에서 새로 연결합니다.')
READ = ('400', '401', '403', '404', '503')
WRITE = ('400', '401', '403', '404', '408', '409', '413', '429', '503')

OPS = {}


def add(method, path, tag, summary, auth, sequence, effects, retry, *, ok=None, base=None, body=None,
        body_note=None, params=(), errors=READ, notes='', executable=None, transform=None):
    if (method, path) in OPS:
        raise RuntimeError('Duplicate iPhone operation ' + method + ' ' + path)
    if tag not in TAGS:
        raise RuntimeError('Unknown iPhone tag ' + tag)
    OPS[(method, path)] = dict(tag=tag, summary=summary, auth=auth, sequence=sequence, effects=effects,
                               retry=retry, ok=ok, base=base, body=body, body_note=body_note,
                               params=list(params), errors=errors, notes=notes, executable=executable, transform=transform)


def ok(schema, description='아래 필드는 실제 handler가 반환하는 정본입니다.', code='200'):
    return {code: {'description': description, 'content': {'application/json': {'schema': schema}}}}


def status(value, description='처리 결과.'):
    return obj({'status': s(value)}, description)


def query(name, description, schema, required=False):
    return dict(name=name, **{'in': 'query'}, required=required, description=description, schema=schema)


def prerequisite(auth):
    kind = auth[0]
    if kind == 'iphone':
        scopes = ', '.join('`' + scope + '`' for scope in auth[1])
        return ('전용 iPhone 호스트에서 `Authorization: Bearer <iPhone 세션 토큰>`이 필요하며 세션에 ' + scopes +
                ' scope가 있어야 합니다. Cookie·Origin 헤더를 보내면 400이고 다른 호스트는 404입니다. '
                '서버는 요청마다 세션 만료·철회와 계정 활성 상태를 다시 확인합니다.')
    if kind == 'pkce':
        return ('인증 헤더 없이 전용 iPhone 호스트로 보냅니다. Cookie·Origin 헤더와 query string은 거절합니다. '
                '앱이 만든 PKCE codeVerifier와 그 SHA-256 codeChallenge가 소유 증명입니다.')
    if kind == 'access':
        return '공개 웹 호스트에서 Cloudflare Access 로그인만 필요합니다. WegoH 개인 세션은 필요하지 않습니다.'
    if kind == 'access-form':
        return ('공개 웹 호스트의 Cloudflare Access 로그인과 같은 Origin이 필요합니다. CSRF는 로그인 화면이 요청·계정마다 '
                '만든 일회성 csrf 필드로 확인합니다.')
    if kind == 'browser':
        return '공개 웹 호스트의 Cloudflare Access와 WegoH 개인 세션, 같은 Origin과 현재 X-WegoH-CSRF가 필요합니다.'
    raise RuntimeError('Unknown authentication ' + kind)


def operation_id(method, path):
    words = re.sub(r'[{}]', '', path).replace('/v1/iphone/', '/').replace('-', '/').replace('_', '/').split('/')
    return 'iphone' + method.capitalize() + ''.join(word[:1].upper() + word[1:] for word in words if word)


# --------------------------------------------------------------------------- 01 login and session
SESSION = obj({'user': obj({'id': ACCOUNT, 'displayName': s('현재 계정 표시 이름.')}, '세션 계정.'),
               'scopes': arr(s('허용 scope.', enum=sorted(SCOPES)), '로그인 당시 동의한 scope. 이후 동의 문구가 늘어도 자동으로 확대되지 않습니다.'),
               'expiresAt': dict(EPOCH, description='세션 만료 Unix epoch 초. 로그인 후 7일입니다.')},
              '현재 iPhone 세션.')
NONCE = s('base64url 43자.', pattern='^[A-Za-z0-9_-]{43}$')
VERIFIER = s('앱이 만든 PKCE codeVerifier. 43~128자 [A-Za-z0-9._~-].', pattern='^[A-Za-z0-9._~-]{43,128}$')
REQUEST_ID = s('로그인 요청 ID.', pattern='^[a-f0-9]{32}$')

# Login request lookups (iphone_sessions.login_request) and the public-host browser routes
# (browser_identity, Access edge, check_origin) answer with their own codes, not the Bearer-session ones.
LOGIN_404 = 'IPHONE_ROUTE_NOT_FOUND(전용 iPhone 호스트가 아닌 주소) 또는 IPHONE_LOGIN_NOT_FOUND(없는 requestId)입니다. 앱에서 새 로그인 요청을 만듭니다.'
LOGIN_410 = 'IPHONE_LOGIN_EXPIRED: 5분 기한이 지난 로그인 요청입니다. 앱에서 새 로그인 요청을 만듭니다.'
BROWSER_401 = ('Access authentication required·Access authentication invalid(Cloudflare Access 로그인 없음·무효) 또는 '
               'IPHONE_LOGIN_REQUIRED(요청에 Access 신원이 없음)입니다. 공개 웹 호스트에서 Access 로그인 후 다시 엽니다.')
BROWSER_404 = 'IPHONE_ROUTE_NOT_FOUND: 공개 웹 호스트가 아닌 주소(전용 iPhone 호스트 포함)로 왔습니다.'
# The public-host edge (app.security_headers -> TeamAuth.boundary -> edge_identity) runs before these handlers.
BROWSER_EDGE_403 = 'Team access denied(Access 계정이 팀 명단에 없거나 비활성이거나 자가 등록 신원과 다름)'
BROWSER_EDGE_503 = ('Access verification unavailable(Access 서명 키 조회 실패), Team authentication unavailable(경계 신원 확인 중 '
                    '저장소·명단 오류)')
BROWSER_429 = 'Request limit exceeded: 계정당 {limit}회/분을 넘었습니다. Retry-After: 60을 따릅니다.'

add('post', '/v1/iphone/login/requests', 'iPhone 01 로그인·세션', 'iPhone 로그인 요청 만들기', ('pkce',),
    '앱이 codeVerifier를 만들고 SHA-256 codeChallenge(base64url, 패딩 없음)와 무작위 state를 보냅니다. 응답의 authorizationUrl을 시스템 브라우저(ASWebAuthenticationSession)로 엽니다.',
    '5분 유효한 PENDING 요청을 저장합니다. 1시간 지난 요청과 하루 지난 만료 세션은 이때 정리됩니다. 아직 계정과 연결되지 않습니다.',
    '응답을 잃으면 새 요청을 만듭니다. 서비스 전체 120회/분 한도입니다.',
    ok=ok(obj({'requestId': REQUEST_ID, 'expiresAt': dict(EPOCH, description='요청 만료 Unix epoch 초(5분).'),
               'authorizationUrl': s('공개 웹 호스트의 /iphone-login?request_id=… 주소.', format='uri')},
              '로그인 승인 화면 주소.'), '로그인 요청을 만들었습니다.', '201'),
    body=obj({'codeChallenge': dict(NONCE, description='codeVerifier의 SHA-256을 base64url로 인코딩한 43자.'),
              'state': dict(NONCE, description='앱이 만든 43자 state. 콜백에서 그대로 돌아오며 앱이 일치를 확인합니다.')},
             '정확히 두 필드. 2048바이트 이하.'),
    errors=dict.fromkeys(('400', '408', '413', '503')) | {
        '404': 'IPHONE_ROUTE_NOT_FOUND: 전용 iPhone 호스트가 아닌 주소로 왔습니다.',
        '429': 'Request limit exceeded: 서비스 전체 로그인 요청 120회/분을 넘었습니다. Retry-After: 60을 따릅니다.'})

add('get', '/iphone-login', 'iPhone 01 로그인·세션', '웹에서 iPhone 로그인 동의 화면 열기', ('access',),
    'POST /v1/iphone/login/requests의 authorizationUrl을 시스템 브라우저로 엽니다. query는 request_id 하나만 허용합니다.',
    '현재 Access 계정 이름과 iPhone 앱이 쓸 기능 범위, 7일 유지 안내를 담은 HTML 동의 화면을 반환합니다. 로그인/거절 버튼은 POST /v1/iphone/browser/login/decision으로 전송됩니다. 화면을 여는 것만으로 승인되지 않습니다.',
    '이미 처리한 요청은 409, 만료는 410입니다. 앱에서 새 로그인 요청을 만듭니다. 계정당 30회/분입니다.',
    ok={'200': {'description': '로그인 동의 HTML. Referrer-Policy: strict-origin이며 CSP form-action에 앱 콜백이 추가됩니다.',
                'content': {'text/html': {'schema': {'type': 'string', 'description': 'HTML 문서.'}}}}},
    params=[query('request_id', 'POST /v1/iphone/login/requests가 반환한 32hex requestId.', REQUEST_ID, True)],
    errors={'400': 'IPHONE_INVALID_REQUEST: query가 request_id(32hex) 하나가 아닙니다. authorizationUrl을 그대로 엽니다.',
            '401': BROWSER_401,
            '403': BROWSER_EDGE_403 + '입니다.',
            '404': BROWSER_404 + ' 없는 request_id는 IPHONE_LOGIN_NOT_FOUND입니다.',
            '409': 'IPHONE_LOGIN_USED: 이미 허용·거절·취소된 요청입니다. 앱에서 새 로그인 요청을 만듭니다.',
            '410': LOGIN_410,
            '429': BROWSER_429.format(limit=30),
            '503': BROWSER_EDGE_503 + ' 또는 Database unavailable(동의 화면 조회 중 저장소 오류)입니다. 잠시 뒤 화면을 다시 엽니다.'},
    executable=False)

add('post', '/v1/iphone/browser/login/decision', 'iPhone 01 로그인·세션', '웹 동의 화면에서 iPhone 로그인 허용 또는 거절', ('access-form',),
    '동의 화면 form이 request_id·csrf·decision(approve/deny) 세 필드를 application/x-www-form-urlencoded로 보냅니다.',
    'approve면 계정을 확인하고 일회성 code를 발급해 io.wegoh.iphone://login/callback?state=…&code=…로 303 이동합니다. deny면 ?state=…&error=access_denied로 이동합니다. code는 해시로만 저장합니다.',
    '이미 처리한 요청은 409입니다. 계정당 15회/분입니다. 콜백을 잃으면 앱에서 새 로그인 요청을 시작합니다.',
    ok={'303': {'description': '앱 콜백으로 이동합니다. Location에 state와 code 또는 error=access_denied가 담기며 Referrer-Policy: no-referrer입니다.',
                'headers': {'Location': {'description': 'io.wegoh.iphone://login/callback?…', 'schema': {'type': 'string'}}}}},
    body=obj({'request_id': REQUEST_ID, 'csrf': s('동의 화면이 계정·요청별로 만든 64hex 값.', pattern='^[a-f0-9]{64}$'),
              'decision': s('사용자 선택.', enum=['approve', 'deny'])}, '정확히 세 필드. 2048바이트 이하.'),
    body_note='application/x-www-form-urlencoded',
    errors={'400': 'IPHONE_INVALID_REQUEST: Content-Type이 application/x-www-form-urlencoded가 아니거나 query가 있거나, '
                   'request_id·csrf·decision 세 필드가 정확히 한 번씩 오지 않았거나 값 형식이 틀렸습니다.',
            '401': BROWSER_401,
            '403': (BROWSER_EDGE_403 + ', Origin denied(Origin이 공개 웹 origin과 다름), IPHONE_LOGIN_CSRF(csrf가 이 계정·요청의 값과 다름) 또는 '
                    'IPHONE_LOGIN_DENIED(승인 시 팀 계정을 쓸 수 없음)입니다. 동의 화면을 다시 엽니다.'),
            '404': BROWSER_404 + ' 없는 request_id는 IPHONE_LOGIN_NOT_FOUND입니다.',
            '408': 'IPHONE_REQUEST_TIMEOUT: form 본문을 5초 안에 받지 못했습니다. 동의 화면을 다시 엽니다.',
            '409': 'IPHONE_LOGIN_USED: 이미 승인·거절·취소된 요청입니다.',
            '410': LOGIN_410,
            '413': 'IPHONE_REQUEST_TOO_LARGE: form 본문이 2048바이트를 넘었습니다.',
            '429': BROWSER_429.format(limit=15),
            '503': (BROWSER_EDGE_503 + ' 또는 IPHONE_SERVICE_UNAVAILABLE(처리 중 저장소 오류)입니다. 승인 여부를 추정하지 말고 '
                    '앱에서 로그인을 다시 시작합니다.')},
    executable=False)

add('post', '/v1/iphone/login/exchange', 'iPhone 01 로그인·세션', '로그인 code를 iPhone 세션 토큰으로 교환', ('pkce',),
    '콜백의 state가 앱이 보낸 값과 같은지 확인한 뒤 requestId·code·codeVerifier를 보냅니다.',
    '승인한 요청이면 7일 Bearer 세션을 만들고 accessToken을 한 번만 반환합니다. 서버는 토큰 해시만 저장하고 요청을 USED로 바꿉니다. scope는 승인 당시 동의 버전(현재 v4)으로 고정됩니다.',
    '아직 승인 전이면 409 IPHONE_LOGIN_PENDING이므로 잠시 후 다시 교환합니다. 이미 교환했으면 409 IPHONE_LOGIN_USED이며 새 로그인을 시작합니다. 서비스 전체 120회/분입니다.',
    ok=ok(dict(SESSION, properties=dict(SESSION['properties'], accessToken=s('iPhone 세션 Bearer 토큰. Keychain에만 보관하고 로그·URL에 넣지 않습니다.'),
                                            tokenType=s('Bearer.', const='Bearer')),
               required=SESSION['required'] + ['accessToken', 'tokenType'], description='새 iPhone 세션.')),
    body=obj({'requestId': REQUEST_ID, 'code': dict(NONCE, description='콜백으로 받은 일회성 code.'), 'codeVerifier': VERIFIER},
             '정확히 세 필드. 2048바이트 이하.'),
    errors=dict.fromkeys(('400', '408', '413', '503')) | {
        '404': LOGIN_404, '410': LOGIN_410,
        '429': 'Request limit exceeded: 서비스 전체 교환 120회/분을 넘었습니다. Retry-After: 60을 따릅니다.',
        '401': 'IPHONE_INVALID_PROOF: codeVerifier 또는 code가 이 요청과 맞지 않습니다.',
        '403': 'IPHONE_LOGIN_DENIED: 사용자가 거절·취소했거나 계정을 더 이상 쓸 수 없습니다.',
        '409': 'IPHONE_LOGIN_PENDING(아직 승인 전) 또는 IPHONE_LOGIN_USED(이미 교환)입니다.'})

add('post', '/v1/iphone/login/cancel', 'iPhone 01 로그인·세션', '진행 중인 iPhone 로그인 요청 취소', ('pkce',),
    '사용자가 앱에서 로그인을 그만두면 requestId와 codeVerifier를 보냅니다.',
    'PENDING·APPROVED 요청을 CANCELLED로 바꾸고 발급된 code를 지웁니다. 이후 교환은 403입니다. 이미 거절·취소된 요청은 그대로 204입니다.',
    '같은 취소 재시도는 204입니다. 이미 교환한 요청은 409이며 그때는 로그아웃을 사용합니다.',
    ok={'204': {'description': '취소했거나 이미 끝난 요청입니다. 본문이 없습니다.'}},
    body=obj({'requestId': REQUEST_ID, 'codeVerifier': VERIFIER}, '정확히 두 필드. 2048바이트 이하.'),
    errors=dict.fromkeys(('400', '408', '413', '503')) | {
        '404': LOGIN_404, '410': LOGIN_410,
        '429': 'Request limit exceeded: 서비스 전체 취소 120회/분을 넘었습니다. Retry-After: 60을 따릅니다.',
        '401': 'IPHONE_INVALID_PROOF: codeVerifier가 이 요청과 맞지 않습니다.',
        '409': 'IPHONE_LOGIN_USED: 이미 세션으로 교환한 요청입니다.'})

add('get', '/v1/iphone/session', 'iPhone 01 로그인·세션', '현재 iPhone 세션 확인', ('iphone', ('account:read',)),
    '앱 시작·복귀 때 저장한 토큰으로 호출합니다. query는 허용하지 않습니다.',
    '세션 계정·scope·만료 시각만 반환합니다. 토큰을 갱신하거나 연장하지 않습니다.',
    '401이면 토큰을 지우고 다시 로그인합니다.', ok=ok(SESSION))

add('delete', '/v1/iphone/session', 'iPhone 01 로그인·세션', '이 iPhone 세션 로그아웃', ('iphone', ('account:read',)),
    '사용자가 로그아웃을 선택하면 본문 없이 호출합니다. query는 허용하지 않습니다.',
    '현재 토큰 세션만 철회합니다. 이 세션에 묶인 푸시 등록은 더 이상 알림을 받지 않습니다. 다른 iPhone 세션과 차량 연결은 그대로입니다.',
    '응답을 잃어도 로컬 토큰을 지우면 됩니다. 이미 철회된 토큰은 401입니다.',
    ok={'204': {'description': '로그아웃했습니다. 본문이 없습니다.'}})

add('post', '/v1/iphone/diagnostics', 'iPhone 02 계정·알림', '앱이 응답을 쓰지 못한 실패 보고', ('iphone', ('account:read',)),
    '서버에 닿지 못했거나 응답을 해석하지 못한 요청을 모아 비동기로 보냅니다. 보고가 실패해도 화면 동작에는 영향이 없습니다.',
    '보고마다 wegoh_client_event_v1 기록과 스팬 이벤트를 남기고 그 트레이스를 보관합니다. 계정·기기 ID 원문과 값은 저장하지 않으며, 마운트되지 않은 경로 항목은 건너뛰고 skipped로 셉니다.',
    '같은 보고를 다시 보내도 기록만 늘어납니다. 429이면 Retry-After를 따르고, 그 밖의 실패는 버립니다.',
    base=('post', '/v1/native/diagnostics'), body='base',
    errors=dict.fromkeys(('400', '408', '503')) | {
        '413': 'DIAGNOSTIC_TOO_LARGE: 본문 8KiB 또는 보고 20개를 넘었습니다.',
        '429': 'RATE_LIMITED: 계정당 분당 30회를 넘었습니다. Retry-After를 따릅니다.'})

add('delete', '/v1/iphone/browser/sessions', 'iPhone 01 로그인·세션', '웹에서 내 모든 iPhone 세션 해제', ('browser',),
    '웹 설정에서 사용자가 iPhone 로그인 전체 해제를 선택했을 때 호출합니다. 본문은 없습니다.',
    '본인 계정의 모든 iPhone 세션을 철회하고, 아직 교환하지 않은 승인 로그인 요청도 취소합니다. 차량 연결과 웹 세션은 그대로입니다.',
    '반복해도 204입니다. 계정당 15회/분입니다.',
    ok={'204': {'description': '모든 iPhone 세션을 해제했습니다. 본문이 없습니다.'}},
    errors={'401': (BROWSER_401 + ' WegoH 개인 세션이 없거나 끝났으면 Start a team session first·Team session expired, '
                    '계정이 비활성이거나 없으면 Account unavailable입니다.'),
            '403': ('Origin denied·CSRF verification failed(같은 Origin과 현재 X-WegoH-CSRF 필요), Action not permitted(세션의 역할이 '
                    '현재 명단 역할과 다름) 또는 ' + BROWSER_EDGE_403 + '입니다.'),
            '404': BROWSER_404,
            '429': BROWSER_429.format(limit=15),
            '503': BROWSER_EDGE_503 + ' 또는 IPHONE_SERVICE_UNAVAILABLE(처리 중 저장소 오류)입니다. 해제 여부를 추정하지 말고 다시 시도합니다.'},
    executable=True)

# --------------------------------------------------------------------------- 02 account and push
ACCOUNT_CHANGED_401 = SESSION_401 + ' 처리 중 다시 확인한 세션 계정이 요청 시작 때와 다르면 Account changed입니다. 저장한 토큰을 지우고 로그인부터 다시 합니다.'
ACCOUNT_ROW_401 = (SESSION_401 + ' 처리 중 다시 확인한 세션 계정이 요청 시작 때와 다르면 Account changed, 저장 직전 계정 행이 없으면 '
                   'INVALID_CREDENTIAL입니다. 저장한 토큰을 지우고 로그인부터 다시 합니다.')
VEHICLE_401 = (SESSION_401 + ' 처리 중 다시 확인한 세션 계정이 요청 시작 때와 다르면 Account changed, 차량 연결이 발급 완료 상태가 아니거나 '
               '계정 행이 없으면 INVALID_CREDENTIAL입니다. 저장한 토큰을 지우고 로그인부터 다시 합니다.')
ACCOUNT_403 = 'IPHONE_SCOPE_DENIED(세션에 account:write 없음) 또는 Team access denied(저장된 계정이 현재 팀 명단과 맞지 않음)입니다.'
PROFILE = obj({'user': obj({'id': ACCOUNT, 'displayName': s('현재 계정 표시 이름.'), 'handle': s('소문자 친구 핸들. @ 제외.')}, '본인 계정.')}, '내 프로필.')
add('get', '/v1/iphone/profile', 'iPhone 02 계정·알림', '내 프로필 이름과 친구 핸들 조회', ('iphone', ('account:read',)),
    'query 없이 호출합니다. 수정 화면은 이 값으로 expectedDisplayName·expectedHandle을 채웁니다.',
    '계정 ID·표시 이름·핸들만 반환합니다. private, no-store입니다.', '계정당 60회/분입니다.',
    ok=ok(PROFILE), errors=READ + ('429',))

add('put', '/v1/iphone/profile/handle', 'iPhone 02 계정·알림', '내 친구 핸들 바꾸기', ('iphone', ('account:write',)),
    '직전 GET /v1/iphone/profile의 handle을 expectedHandle로, 새 핸들을 handle로 보냅니다.',
    '핸들을 소문자로 저장합니다. 같은 값이면 변경 없이 성공합니다. 실제 변경은 24시간에 한 번입니다.',
    '409 HANDLE_CHANGED는 다시 조회 후 저장, HANDLE_UNAVAILABLE은 다른 핸들을 고릅니다. 429 HANDLE_CHANGE_LIMIT는 Retry-After 86400초를 따릅니다. 시도는 계정당 5회/분입니다.',
    base=('put', '/v1/profile/handle'), body='base',
    errors=dict.fromkeys(('404', '409', '429', '503')) | {
        '400': ('IPHONE_INVALID_REQUEST(query·Cookie·Origin), Invalid JSON(본문이 JSON이 아님), Invalid request fields(handle·expectedHandle '
                '두 필드가 아님) 또는 INVALID_HANDLE(핸들 형식)입니다.'),
        '401': ACCOUNT_CHANGED_401,
        '403': ('IPHONE_SCOPE_DENIED(세션에 account:write 없음) 또는 Account unavailable(저장 직전 계정이 비활성이거나 없음)입니다.'),
        '413': 'Request too large: 본문이 4096바이트를 넘었습니다. 내용을 잘라 보내지 말고 사용자가 줄이게 합니다.'},
    notes='본문은 4096바이트 이하 JSON입니다.')

add('put', '/v1/iphone/profile', 'iPhone 02 계정·알림', '내 표시 이름 바꾸기', ('iphone', ('account:write',)),
    '직전 조회의 표시 이름을 expectedDisplayName으로 보내고 새 이름(1~30자, 양끝 공백·제어문자 금지)을 displayName으로 보냅니다.',
    '암호화된 계정 정보의 표시 이름을 바꾸고 연결 차량에 변경을 알립니다.',
    '409 PROFILE_CHANGED면 다시 조회해 확인합니다. 400 INVALID_PROFILE은 입력을 고칩니다. 계정당 15회/분입니다.',
    base=('put', '/v1/profile'), body='base',
    errors=dict.fromkeys(WRITE) | NATIVE_BODY | {
        '400': ('IPHONE_INVALID_REQUEST(query·Cookie·Origin), INVALID_REQUEST(Content-Type) 또는 INVALID_PROFILE(필드·이름 형식, '
                '1024바이트를 넘는 본문)입니다. 12288바이트를 넘는 본문만 413입니다.'),
        '401': ACCOUNT_ROW_401, '403': ACCOUNT_403},
    notes='본문은 Content-Type: application/json, 1024바이트 이하입니다.')

INSTALLATION = s('앱 설치 ID(UUID). 기기에 저장해 재사용합니다.', format='uuid')
add('put', '/v1/iphone/push/installation', 'iPhone 02 계정·알림', '이 iPhone의 푸시 알림 기기 등록', ('iphone', ('account:read',)),
    '알림 허용 후 APNs deviceToken(소문자 hex)과 환경을 보냅니다. 토큰이 바뀔 때마다 다시 호출합니다.',
    '토큰을 암호화해 현재 세션에 묶어 저장합니다. 같은 토큰을 다른 설치가 갖고 있었으면 그 등록을 지웁니다. 알림은 친구 요청·수락(friends:read), 여행 초대·손들기·손들기 반응(trips:read)뿐이며 세션이 끝나면 보내지 않습니다.',
    '같은 값 재등록은 등록 시각만 갱신합니다. 계정당 60회/분입니다.',
    ok=ok(obj({'registered': {'const': True, 'description': '등록됨.'}}, '등록 결과.')),
    body=obj({'installationId': INSTALLATION, 'deviceToken': s('APNs deviceToken 소문자 hex 64~512자.', pattern='^(?:[0-9a-f]{2}){32,256}$'),
              'environment': s('APNs 환경.', enum=['sandbox', 'production'])}, '정확히 세 필드. 2048바이트 이하.'),
    errors=('400', '401', '403', '404', '408', '413', '429', '503'))

add('delete', '/v1/iphone/push/installation', 'iPhone 02 계정·알림', '이 iPhone의 푸시 알림 등록 해제', ('iphone', ('account:read',)),
    '알림을 끄거나 로그아웃하기 전에 installationId를 보냅니다.',
    '현재 세션·계정에 묶인 해당 설치 등록만 지웁니다. 없으면 그대로 성공합니다.',
    '반복해도 registered=false입니다. 계정당 60회/분입니다.',
    ok=ok(obj({'registered': {'const': False, 'description': '등록 없음.'}}, '해제 결과.')),
    body=obj({'installationId': INSTALLATION}, '정확히 한 필드. 2048바이트 이하.'), errors=('400', '401', '403', '404', '408', '413', '429', '503'))

# --------------------------------------------------------------------------- 03 vehicle connection
# iphone_vehicles.py: GET reads only the code; POST/DELETE read the body with native read_body.
CONNECTION_ERRORS = {
    '404': 'OPERATION_NOT_FOUND(없는 코드·다른 계정이 처리한 코드) 또는 IPHONE_ROUTE_NOT_FOUND입니다.',
    '410': 'AUTHORIZATION_EXPIRED: 코드 기한이 지났습니다. 차량에서 새 코드를 받습니다.',
    '429': 'RATE_LIMITED: 계정당 60회/분을 넘었습니다. Retry-After를 따릅니다.'}
CONNECTION_BODY = dict(NATIVE_BODY, **{
    '400': 'INVALID_COMPARISON_CODE(코드 형식), IPHONE_INVALID_REQUEST(Cookie·Origin 헤더) 또는 INVALID_REQUEST(Content-Type·본문·동의 형식)입니다.'})
add('get', '/v1/iphone/connections/{user_code}', 'iPhone 03 차량 연결', '차량 연결 코드 내용 확인', ('iphone', ('vehicles:manage',)),
    '차량 화면의 8자 코드를 입력하면 호출합니다. 차량 이름·요청 scope·공개 문구를 사용자에게 보여 줍니다.',
    '현재 요청 상태와 동의 snapshot을 반환합니다. 조회만으로 허용되지 않습니다. 본인이 이미 처리한 코드는 상태를 보여 주고 다른 계정이 처리한 코드는 404입니다.',
    '조회는 안전합니다. 410이면 차량에서 새 코드를 받습니다.',
    base=('get', '/v1/connections/{user_code}'), errors=dict.fromkeys(('401', '403', '503')) | CONNECTION_ERRORS | {
        '400': 'INVALID_COMPARISON_CODE(코드 형식) 또는 IPHONE_INVALID_REQUEST(Cookie·Origin 헤더)입니다.'})

add('post', '/v1/iphone/connections/{user_code}', 'iPhone 03 차량 연결', '확인한 차량에 내 계정 연결 허용', ('iphone', ('vehicles:manage',)),
    'GET으로 받은 disclosureSnapshot과 사용자가 고른 scope로 동의 본문을 만들어 보냅니다.',
    '필수 scope가 모두 있으면 APPROVED와 연결 grant를 만들고, 아니면 DENIED로 기록합니다. 차량이 교환을 마쳐야 실제 연결이 끝납니다.',
    'iPhone에서 이미 처리한 코드는 다시 허용·취소할 수 없어 409입니다. 연결 해제는 DELETE /v1/iphone/vehicles/{device_id}를 사용합니다.',
    base=('post', '/v1/connections/{user_code}'), body='base',
    errors=dict.fromkeys(('401', '403', '503')) | CONNECTION_ERRORS | CONNECTION_BODY | {
        '409': 'OPERATION_CONFLICT(이미 허용·취소한 코드), CONSENT_CHANGED(동의 문구 변경) 또는 VEHICLE_CONNECTION_LIMIT(연결 차량 한도)입니다.'})

add('delete', '/v1/iphone/connections/{user_code}', 'iPhone 03 차량 연결', '차량 연결 코드 취소', ('iphone', ('vehicles:manage',)),
    '사용자가 허용하지 않고 취소하면 {"authorizationVersion":1}을 보냅니다.',
    '아직 처리되지 않은 코드를 DENIED로 기록해 차량 교환을 막습니다. 이미 허용한 연결은 이 경로로 철회하지 않습니다.',
    '이미 처리한 코드는 409, 만료는 410입니다. 연결된 차량을 끊으려면 차량 목록에서 해제합니다.',
    base=('delete', '/v1/connections/{user_code}'), body='base',
    errors=dict.fromkeys(('401', '403', '503')) | CONNECTION_ERRORS | CONNECTION_BODY | {
        '409': 'OPERATION_CONFLICT: 이미 허용·거절·취소한 코드입니다. 허용한 연결은 차량 목록에서 해제합니다.'})

add('get', '/v1/iphone/vehicles', 'iPhone 03 차량 연결', '내 연결 차량 목록', ('iphone', ('vehicles:manage',)),
    'query 없이 호출합니다. 각 항목의 deviceId로 프로필·기능 공유·해제를 호출합니다.',
    '현재 본인 계정의 살아 있는 차량 연결만 반환합니다.', '계정당 60회/분(429 RATE_LIMITED)입니다.',
    base=('get', '/v1/devices'), errors=READ + ('429',))

add('delete', '/v1/iphone/vehicles/{device_id}', 'iPhone 03 차량 연결', '연결 차량 해제', ('iphone', ('vehicles:manage',)),
    '목록에서 고른 차량을 사용자가 명시 해제할 때 본문 없이 호출합니다.',
    '해당 차량의 연결 grant를 철회합니다. 차량은 다음 요청부터 거절되며 그 차량이 허용한 여행 리모컨과 대기 명령도 정리됩니다.',
    '이미 해제한 차량은 404 DEVICE_UNAVAILABLE입니다. 계정당 60회/분입니다.',
    ok=ok(status('revoked', '해제 결과.')), errors=READ + ('429',))

add('get', '/v1/iphone/vehicles/{device}/profile', 'iPhone 03 차량 연결', '연결 차량의 이름과 번호판 조회', ('iphone', ('account:write',)),
    'query 없이 호출합니다. 수정 전 revision을 이 응답에서 받습니다.',
    '본인이 정한 차량 이름·번호판과 기본 이름, revision을 반환합니다. private, no-store입니다.',
    '없는 차량은 404 DEVICE_UNAVAILABLE입니다. 계정당 60회/분입니다.',
    base=('get', '/v1/devices/{device}/vehicle-profile'), errors=dict.fromkeys(READ + ('429',)) | {'410': GRANT_EXPIRED,
        '401': VEHICLE_401,
        '403': 'IPHONE_SCOPE_DENIED(세션에 account:write 없음), CONSENT_REVOKED(철회된 차량 연결) 또는 Team access denied(기본 차량 이름을 정할 팀 명단 정보 없음)입니다.',
        '400': 'Invalid request(query) 또는 IPHONE_INVALID_REQUEST(Cookie·Origin 헤더)입니다.'})

add('put', '/v1/iphone/vehicles/{device}/profile', 'iPhone 03 차량 연결', '연결 차량의 이름과 번호판 저장', ('iphone', ('account:write',)),
    '직전 GET의 revision을 expectedRevision으로, plateNumber(빈 문자열은 해제)와 name을 보냅니다.',
    '차량 프로필을 저장하고 revision을 1 올립니다. 연결 차량 앱에 변경을 알립니다. 친구 프로필에는 현재 연결 차량의 번호판만 보입니다.',
    '409 VEHICLE_PROFILE_CHANGED면 다시 조회합니다. 계정당 30회/분입니다.',
    base=('put', '/v1/devices/{device}/vehicle-profile'), body='base',
    errors=dict.fromkeys(WRITE) | NATIVE_BODY | {'410': GRANT_EXPIRED,
        '400': ('Invalid request(query), IPHONE_INVALID_REQUEST(Cookie·Origin), INVALID_REQUEST(Content-Type) 또는 '
                'INVALID_VEHICLE_PROFILE(필드·번호판·이름 형식, 1024바이트를 넘는 본문)입니다. 12288바이트를 넘는 본문만 413입니다.'),
        '401': VEHICLE_401,
        '403': 'IPHONE_SCOPE_DENIED(세션에 account:write 없음), CONSENT_REVOKED(철회된 차량 연결) 또는 Team access denied(기본 차량 이름을 정할 팀 명단 정보 없음)입니다.'},
    notes='본문은 Content-Type: application/json, 1024바이트 이하입니다.')

FUNCTIONAL = obj({
    'authorization': ref('NativeFunctionalSnapshot', '현재 기능 동의 정본.'),
    'approvedDisclosureVersion': nullable(n('현재 유효한 동의가 승인한 기능 공개 문구 버전. 유효한 동의가 없으면 null.', minimum=1)),
    'disclosure': obj({'version': n('현재 기능 공개 문구 버전.', minimum=1), 'sha256': s('현재 공개 문구 SHA-256.', pattern='^[a-f0-9]{64}$'),
                       'purposes': arr(obj({'id': s('기능 목적 ID.'), 'label': s('화면 이름.'), 'dataCategories': arr(s('데이터 종류.'), '사용하는 데이터.'),
                                            'purpose': s('사용 목적.'), 'retention': s('보관 기간.'), 'withdrawal': s('철회 방법.'),
                                            'refusal': s('거부 시 영향.'), 'default': b('신규 연결의 기본값.')}, '기능 목적 공개 항목.'),
                                       '현재 기능 목적 공개 목록.')}, '사용자에게 보여 줄 현재 공개 문구.'),
    'readOnlyPurposes': arr(s('iPhone에서 바꿀 수 없는 목적.'), '계정 기본 목적과 차량에서만 바꾸는 명령 받기(device-commands:receive).'),
}, 'iPhone 기능 공유 설정 화면 데이터.')
add('get', '/v1/iphone/vehicles/{device}/functional-permissions', 'iPhone 03 차량 연결', '연결 차량의 기능 공유 설정 보기', ('iphone', ('vehicles:manage',)),
    'query 없이 호출합니다. 저장 전 authorization.revision과 disclosure를 화면에 씁니다.',
    '현재 기능 동의 snapshot과 공개 문구, iPhone에서 바꿀 수 없는 목적을 반환합니다. private, no-store입니다.',
    '없는 차량은 404 DEVICE_UNAVAILABLE, 기능이 꺼진 배포는 404 ROUTE_NOT_FOUND입니다.',
    ok=ok(FUNCTIONAL))

add('put', '/v1/iphone/vehicles/{device}/functional-permissions', 'iPhone 03 차량 연결', '연결 차량의 기능 공유 선택 저장', ('iphone', ('vehicles:manage',)),
    '직전 GET의 grantId·revision과 사용자가 고른 approvedPurposes, 현재 disclosure 버전·SHA-256을 보냅니다.',
    '선택 목적을 저장하고 revision을 올립니다. 끈 목적의 공유 효과는 정리합니다. 계정 기본 목적은 유지되며 명령 받기(device-commands:receive)는 차량에서만 바꿀 수 있습니다.',
    '409 FUNCTIONAL_REVISION_CHANGED·DEVICE_BINDING_CHANGED면 다시 조회합니다. 계정당 60회/분입니다.',
    ok=ok(FUNCTIONAL), body=ref('NativeFunctionalConsent', '기능 공유 선택. 12288바이트 이하.'),
    errors=WRITE, notes='403 RECEIVER_VEHICLE_ONLY는 명령 받기를 iPhone에서 바꾸려 한 경우입니다.')

# --------------------------------------------------------------------------- 04 friends
add('get', '/v1/iphone/friends/search', 'iPhone 04 친구', '친구 핸들 정확 일치 검색', ('iphone', ('friends:read',)),
    'handle query 하나만 보냅니다. 선택적 @와 3~20자 영문·숫자·밑줄·점이며 대소문자를 구분하지 않습니다.',
    '활성 계정 한 명의 id·name·handle·relationship(self/friend/incoming/outgoing/none)만 반환합니다. 없거나 차단 관계면 person:null입니다.',
    '계정당 20회/분, 접속 IP당 60회/분입니다. 400 INVALID_HANDLE은 입력을 고칩니다.',
    base=('get', '/v1/social/friends/search'),
    params=[query('handle', '정확한 친구 핸들. 선택적 @, 대소문자 무시.', s('핸들.', maxLength=21, pattern='^@?[A-Za-z0-9][A-Za-z0-9_.]{2,19}$'), True)],
    errors=READ + ('429',))

FRIEND_ITEM = obj({'id': ACCOUNT, 'name': s('표시 이름.'), 'handle': s('소문자 핸들.')}, '친구 계정.')
add('get', '/v1/iphone/friends', 'iPhone 04 친구', '친구·요청·차단 목록', ('iphone', ('friends:read',)),
    'query 없이 호출합니다. incoming 요청은 respond, outgoing은 DELETE /v1/iphone/friends/{target}로 취소합니다.',
    '현재 친구(차량 보유 여부 포함), 받은·보낸 요청, 내가 차단한 계정을 반환합니다. 웹 overview와 달리 방·기록·capabilities는 없고 handle을 포함합니다.',
    '조회는 안전합니다. 알림을 받으면 다시 읽습니다.',
    ok=ok(obj({'friends': arr(dict(FRIEND_ITEM, properties=dict(FRIEND_ITEM['properties'], hasVehicle=b('번호판을 등록한 현재 연결 차량이 있는지 여부.')),
                                    required=FRIEND_ITEM['required'] + ['hasVehicle']), '수락한 친구.'),
               'requests': arr(dict(FRIEND_ITEM, properties=dict(FRIEND_ITEM['properties'], direction=s('incoming 또는 outgoing.', enum=['incoming', 'outgoing'])),
                                     required=FRIEND_ITEM['required'] + ['direction']), '처리 전 요청.'),
               'blocks': arr(obj({'id': ACCOUNT, 'name': nullable(s('계정이 비활성이면 null.')), 'handle': s('활성 계정이면 핸들.'),
                                  'available': b('대상 계정이 현재 활성인지 여부.')}, '내가 차단한 계정.', required=['id', 'name', 'available']), '내 차단 목록.')},
              'iPhone 친구 화면 데이터.')))

add('get', '/v1/iphone/friends/{peer}/profile', 'iPhone 04 친구', '친구 프로필의 이름과 등록 차량 번호 조회', ('iphone', ('friends:read',)),
    '친구 목록에서 고른 상대 계정 ID로 호출합니다. query는 허용하지 않습니다.',
    '표시 이름과 현재 연결 차량에 등록한 번호 목록을 반환합니다. private, no-store입니다.',
    '친구가 아니거나 차단 관계면 404입니다.', base=('get', '/v1/social/friends/{peer}/profile'))

add('post', '/v1/iphone/friends/requests', 'iPhone 04 친구', '친구 요청 보내기', ('iphone', ('friends:manage',)),
    '검색 결과의 계정 id를 targetId로 보냅니다.',
    '관계를 pending으로 저장하고 상대 iPhone에 친구 요청 알림을 예약합니다. 이미 보낸 요청이나 친구면 200입니다.',
    '상대가 먼저 보낸 요청이 있으면 409이며 respond를 사용합니다. 계정당 60회/분입니다.',
    base=('post', '/v1/social/friends/requests'), body='base', errors=WRITE)

add('post', '/v1/iphone/friends/requests/{target}/respond', 'iPhone 04 친구', '받은 친구 요청 수락 또는 거절', ('iphone', ('friends:manage',)),
    'incoming 요청 상대 ID를 경로에 넣고 accept:true/false를 보냅니다.',
    '수락하면 친구가 되고 요청자에게 수락 알림을 예약합니다. 거절하면 관계가 없어집니다.',
    '이미 처리했거나 없는 요청은 404입니다. 계정당 60회/분입니다.',
    base=('post', '/v1/social/friends/requests/{target}/respond'), body='base', errors=WRITE)

add('delete', '/v1/iphone/friends/{target}', 'iPhone 04 친구', '보낸 요청 취소 또는 친구 연결 해제', ('iphone', ('friends:manage',)),
    '보낸 요청 취소나 친구 해제를 고르면 {}를 보냅니다.',
    '관계를 없애고 관련 기록·주의 공유와 여행 리모컨 허용을 철회합니다.',
    '받은 요청은 403이며 respond로 거절합니다. 반복은 removed입니다. 계정당 60회/분입니다.',
    base=('delete', '/v1/social/friends/{target}'), body=EMPTY, errors=WRITE)

add('post', '/v1/iphone/blocks', 'iPhone 04 친구', '계정 차단', ('iphone', ('friends:manage',)),
    '대상 계정 ID를 targetId로 보냅니다.',
    '친구·요청을 끝내고 서로 검색·조회를 막습니다. 같은 여행·방에서 관계에 따라 상대 또는 나를 내보냅니다.',
    '이미 차단했으면 200입니다. 계정당 60회/분입니다.',
    base=('post', '/v1/social/blocks'), body='base', errors=WRITE)

add('delete', '/v1/iphone/blocks/{target}', 'iPhone 04 친구', '내 차단 해제', ('iphone', ('friends:manage',)),
    '차단 목록의 계정 ID로 {}를 보냅니다.',
    '내 차단만 제거합니다. 친구 관계·여행 참여는 되살리지 않습니다.',
    '반복은 unblocked입니다. 계정당 60회/분입니다.',
    base=('delete', '/v1/social/blocks/{target}'), body=EMPTY, errors=WRITE)

# --------------------------------------------------------------------------- 05 courses and maps
add('get', '/v1/iphone/places/search', 'iPhone 05 코스·지도', '장소 검색', ('iphone', ('maps:read',)),
    'q(2~60자)와 선택적 지도 중심 x·y를 보냅니다.',
    '공급자 장소 후보를 반환합니다. 검색어와 좌표를 저장하지 않습니다.',
    '429는 Retry-After 60초를 따릅니다.', base=('get', '/v1/places/search'),
    params=[query('q', 'trim 후 2~60자 이름 또는 주소. 제어문자·중복 파라미터는 거절합니다.', s('검색어.', minLength=2, maxLength=60), True),
            query('x', '지도 중심 경도. y와 함께 보내거나 함께 생략합니다.', {'type': 'number', 'minimum': -180, 'maximum': 180, 'description': '경도.'}),
            query('y', '지도 중심 위도. x와 함께 보내거나 함께 생략합니다.', {'type': 'number', 'minimum': -90, 'maximum': 90, 'description': '위도.'})],
    errors=dict.fromkeys(('403', '404')) | {
        '400': 'IPHONE_INVALID_REQUEST(Cookie·Origin 헤더) 또는 PLACE_SEARCH_QUERY_INVALID(q 문자수·제어문자, x/y 조합·범위, 알 수 없는 또는 중복 파라미터)입니다.',
        '401': SESSION_401 + ' 검색 뒤 다시 확인한 세션 계정이 다르면 Authentication changed입니다. 저장한 토큰을 지우고 로그인부터 다시 합니다.',
        '429': 'PLACE_SEARCH_RATE_LIMITED: 계정당 최근 60초 30회를 넘었습니다. Retry-After: 60 이후 다시 검색합니다.',
        '502': 'PLACE_SEARCH_PROVIDER_UNAVAILABLE: 외부 인증·쿼터·리다이렉트·잘못된 응답입니다. 외부 본문은 반환하지 않습니다.',
        '503': ('PLACE_SEARCH_UNAVAILABLE(서버 REST 키 파일이 없거나 안전하지 않음), PLACE_SEARCH_BUSY(프로세스 전체 검색 4개 실행 중) 또는 '
                'IPHONE_SERVICE_UNAVAILABLE(세션·요청 한도 저장소 오류)입니다. 잠시 후 다시 검색합니다.'),
        '504': 'PLACE_SEARCH_TIMEOUT: 검색 전체 3초 제한을 넘었습니다. 늦은 결과는 버립니다.'},
    notes='Cookie·Origin 헤더는 400입니다.')

add('post', '/v1/iphone/routes/preview', 'iPhone 05 코스·지도', '자동차 경로 미리보기', ('iphone', ('maps:read',)),
    '경로 점 목록을 보냅니다.',
    '저장하지 않는 자동차 경로 거리·시간·선을 반환합니다.',
    '429는 Retry-After 60초를 따릅니다.', base=('post', '/v1/routes/preview'), body='base',
    errors=dict.fromkeys(('403', '404')) | {
        '401': SESSION_401 + ' 계산 뒤 다시 확인한 세션 계정이 다르면 Authentication changed입니다. 저장한 토큰을 지우고 로그인부터 다시 합니다.',
        '400': 'IPHONE_INVALID_REQUEST(Cookie·Origin 헤더), Invalid JSON 또는 ROUTE_INPUT_INVALID(알 수 없는 필드·좌표 범위·숫자 형식·장소 1~3개)입니다.',
        '413': 'Pack exceeds 256 KiB: 본문이 262144바이트를 넘었습니다.',
        '422': 'ROUTE_NOT_FOUND: 공급자가 경로를 찾지 못했습니다. 마커만 표시하고 위치를 다시 확인합니다.',
        '429': 'ROUTE_RATE_LIMITED: 최근 60초 20회 초과. Retry-After: 60.',
        '502': 'ROUTE_PROVIDER_UNAVAILABLE: 외부 인증·쿼터·리다이렉트·응답 오류. 외부 본문이나 키는 반환하지 않습니다.',
        '503': 'ROUTE_UNAVAILABLE: 서버 REST 키 파일이 없습니다. ROUTE_BUSY: 전체 동시 작업 4개가 실행 중입니다.',
        '504': 'ROUTE_TIMEOUT: 전체 4초 제한을 넘었습니다. 늦은 결과를 버립니다.'})

OWN_COURSE = obj({'id': s('코스 ID.'), 'version': n('최신 버전.', minimum=1), 'title': s('제목.'), 'author': s('작성자 이름.'),
                  'description': s('설명.'), 'stopCount': n('장소 수 1~3.', minimum=1, maximum=3), 'checksum': s('SHA-256.', pattern='^[a-f0-9]{64}$'),
                  'state': s('approved=공개 중, quarantined/rejected=신고·운영 제한.'), 'stopNames': arr(s('장소 이름.'), '장소 이름 순서.'),
                  'stops': CARD_STOPS}, '내 코스 카드.')
add('get', '/v1/iphone/courses', 'iPhone 05 코스·지도', '내가 게시한 코스 목록', ('iphone', ('courses:read',)),
    'query 없이 호출합니다.', '내 코스별 최신 버전을 최근순 최대 1000개 반환합니다. 카드 지도용 stops를 포함합니다.',
    '계정당 60회/분입니다.', ok=ok(obj({'packs': arr(OWN_COURSE, '내 코스.')}, '내 코스 목록.')), errors=READ + ('429',))

add('get', '/v1/iphone/courses/{pack_id}/versions/{version}', 'iPhone 05 코스·지도', '내 코스 한 버전의 원본과 편집 정보', ('iphone', ('courses:read',)),
    '내 코스 목록의 id·version으로 호출합니다.',
    '불변 코스 JSON과 태그, 대표 이미지 여부, 재창작 초안 ID를 반환합니다. 다른 사람 코스는 404입니다.',
    '계정당 60회/분입니다.',
    ok=ok(obj({'pack': ref('DrivePack', '게시한 코스 JSON.'), 'remixDraftId': nullable(s('이 코스를 만든 재창작 초안 ID.', pattern='^[a-f0-9]{32}$')),
               'tags': arr(s('태그.'), '버전 태그.'), 'hasCover': b('대표 이미지가 있는지 여부.')}, '내 코스 상세.')),
    errors=READ + ('422', '429'))

PUBLISH = {'allOf': [ref('PublishedCourse'), obj({'pack': ref('DrivePack', '서버가 작성자 이름을 넣어 저장한 코스 JSON.')}, 'iPhone은 저장한 코스 JSON을 함께 받습니다.')],
           'description': '게시 결과.'}
add('post', '/v1/iphone/courses', 'iPhone 05 코스·지도', '코스 게시 또는 새 버전 게시', ('iphone', ('courses:write',)),
    'creator·admin 역할만 호출할 수 있습니다. rightsConfirmed:true와 pack, 선택적 tags·coverImage(base64 JPEG 120KiB 이하)·copyCoverFromVersion·remixDraftId를 보냅니다.',
    '새 버전을 즉시 공개(approved)하고 author를 현재 계정 이름으로 바꿉니다. 같은 버전·같은 내용 재전송은 200입니다.',
    '409는 다른 작성자 ID, 연속 버전이 아님, 게시본 불변 위반입니다. 429는 이미지 처리 중이니 Retry-After 1초 뒤 다시 보냅니다. 계정당 60회/분입니다.',
    ok={**ok(PUBLISH, '새 버전을 게시했습니다.', '201'), **ok(PUBLISH, '이미 같은 내용으로 게시된 버전입니다.')},
    base=('post', '/v1/packs'), body='base',
    errors=dict.fromkeys(WRITE) | {'408': 'Request timeout: 본문을 5초 안에 받지 못했습니다. 내 코스 목록으로 게시 여부를 확인한 뒤 다시 보냅니다.',
                                   '413': 'Pack exceeds 256 KiB: 본문 또는 정규화한 코스 JSON이 256KiB를 넘었습니다.'},
    notes='Content-Type: application/json이 필요하며 본문은 256KiB 이하, 수신 5초 이내입니다.')

add('post', '/v1/iphone/courses/public/{pack_id}/versions/{version}/copy', 'iPhone 05 코스·지도', '공개 코스를 내 편집 초안으로 복사', ('iphone', ('courses:write',)),
    'creator·admin 역할만 호출합니다. 본문은 {}입니다.',
    '원작자가 재사용을 허용한 현재 공개 코스(또는 내 코스)로 새 편집 초안과 remixDraftId를 만듭니다. 게시는 POST /v1/iphone/courses로 별도 진행합니다.',
    '새 POST마다 새 초안입니다. 초안은 계정당 500개입니다(409). 계정당 60회/분입니다.',
    ok=ok(obj({'pack': ref('DrivePack', '편집할 새 코스 JSON.'), 'remixDraftId': s('게시 때 보낼 초안 ID.', pattern='^[a-f0-9]{32}$'),
               'tags': arr(s('태그.'), '원본 태그.'), 'hasCover': b('원본 대표 이미지를 첫 게시에 이어받는지 여부.')}, '새 편집 초안.'),
          '초안을 만들었습니다.', '201'),
    body=EMPTY, errors=WRITE + ('422',))


def card_library(schema):
    for key in ('public', 'saved', 'news', 'courses'):
        node = schema.get('properties', {}).get(key)
        if node and isinstance(node.get('items'), dict):
            node['items'] = {'allOf': [node['items'], obj({'stops': CARD_STOPS}, 'iPhone 카드 지도.')],
                             'description': node['items'].get('description', '코스 카드.')}
    return schema


add('get', '/v1/iphone/courses/library', 'iPhone 05 코스·지도', '공개 코스 라이브러리', ('iphone', ('courses:read',)),
    '선택적 q(최대 100자)와 tag(최대 8개, AND)를 보냅니다.',
    '공개·별표·소식·구독 목록을 반환합니다. iPhone 카드에는 지도용 stops가 붙습니다. 숨긴 코스와 차단 관계 제작자는 빠집니다.',
    '조회는 안전합니다.', base=('get', '/v1/native/courses/library'),
    params=[query('q', '제목·설명·제작자·태그 검색. 최대 100자, 앞의 #은 무시합니다.', s('검색어.', maxLength=100)),
            dict(name='tag', required=False, description='최대 8개. 대소문자 구분 없이 AND로 적용합니다.', style='form', explode=True,
                 schema=dict(arr(s('태그.', maxLength=24), '태그 목록.'), maxItems=8), **{'in': 'query'})],
    transform=card_library)

add('get', '/v1/iphone/courses/public/{pack_id}/versions/{version}', 'iPhone 05 코스·지도', '공개 코스 상세', ('iphone', ('courses:read',)),
    '라이브러리 항목의 id·version으로 호출합니다. query는 허용하지 않습니다.',
    'SHA-256을 확인한 코스 JSON과 통계, 구독 가능 여부를 반환합니다. 현재 공개가 아니거나 차단 관계 제작자면 404입니다.',
    '조회는 안전합니다.', base=('get', '/v1/native/courses/public/{pack_id}/versions/{version}'), errors=READ + ('422',))

add('get', '/v1/iphone/courses/public/{pack_id}/versions/{version}/cover', 'iPhone 05 코스·지도', '공개 코스 대표 이미지', ('iphone', ('courses:read',)),
    '상세의 hasCover가 true일 때 호출합니다.',
    '현재 볼 수 있는 공개 코스의 대표 JPEG를 반환합니다. private, no-store, no-transform입니다.',
    '대표 이미지가 없으면 404 Course cover unavailable입니다.',
    ok={'200': {'description': '대표 JPEG.', 'content': {'image/jpeg': {'schema': {'type': 'string', 'format': 'binary', 'description': 'JPEG 바이트.'}}}}},
    errors=READ + ('422',), executable=False)

add('get', '/v1/iphone/courses/creators/{creator_id}', 'iPhone 05 코스·지도', '제작자 프로필과 공개 코스', ('iphone', ('courses:read',)),
    '코스 상세의 creatorId로 호출합니다.', '제작자 이름·통계·내 구독 상태와 최신 공개 코스(카드 stops 포함)를 반환합니다.',
    '공개 코스가 없거나 차단 관계면 404입니다.', base=('get', '/v1/native/courses/creators/{creator_id}'),
    transform=card_library)

COURSE_WRITE = READ + ('408', '413', '429')
add('put', '/v1/iphone/courses/stars/{pack_id}/versions/{version}', 'iPhone 05 코스·지도', '공개 코스 별표', ('iphone', ('courses:write',)),
    '본문은 비우거나 {}입니다.', '현재 공개이고 볼 수 있는 코스 버전에 별표를 남깁니다. 반복해도 같습니다.',
    '계정당 60회/분입니다.', base=('put', '/v1/studio/course-stars/{pack_id}/versions/{version}'), body=EMPTY_OPTIONAL,
    errors=COURSE_WRITE + ('422',))
add('delete', '/v1/iphone/courses/stars/{pack_id}/versions/{version}', 'iPhone 05 코스·지도', '공개 코스 별표 해제', ('iphone', ('courses:write',)),
    '본문은 비우거나 {}입니다.', '내 별표만 지웁니다. 없어도 성공합니다.', '계정당 60회/분입니다.',
    base=('delete', '/v1/studio/course-stars/{pack_id}/versions/{version}'), body=EMPTY_OPTIONAL, errors=COURSE_WRITE + ('422',))
add('put', '/v1/iphone/courses/follows/{pack_id}/versions/{version}', 'iPhone 05 코스·지도', '코스 제작자 구독', ('iphone', ('courses:write',)),
    '구독할 제작자의 공개 코스 id·version으로 호출합니다. 본문은 비우거나 {}입니다.',
    '제작자 구독을 만들고 followId를 반환합니다. 이후 새 공개 코스가 소식에 나타납니다. 본인·차단 관계는 404입니다.',
    '반복해도 같은 followId입니다. 계정당 60회/분입니다.',
    base=('put', '/v1/studio/course-follows/{pack_id}/versions/{version}'), body=EMPTY_OPTIONAL, errors=COURSE_WRITE + ('422',))
add('delete', '/v1/iphone/courses/follows/{follow_id}', 'iPhone 05 코스·지도', '코스 제작자 구독 취소', ('iphone', ('courses:write',)),
    '구독 응답이나 제작자 상세의 followId로 호출합니다. 본문은 비우거나 {}입니다.',
    '내 구독만 지웁니다. 없어도 following=false입니다. UUID가 아니면 404입니다.', '계정당 60회/분입니다.',
    base=('delete', '/v1/studio/course-follows/{follow_id}'), body=EMPTY_OPTIONAL, errors=COURSE_WRITE)
TAG_FOLLOW = ok(obj({'following': b('구독 여부.'), 'tag': s('저장된 태그 표기.')}, '태그 구독 상태.'))
add('put', '/v1/iphone/courses/tag-follows/{tag}', 'iPhone 05 코스·지도', '코스 태그 구독', ('iphone', ('courses:write',)),
    '라이브러리에 보이는 태그로 호출합니다. 본문은 비우거나 {}입니다.',
    '현재 공개 코스에 있는 태그만 구독합니다. 없는 태그는 404 Tag unavailable입니다.', '계정당 60회/분입니다.',
    ok=TAG_FOLLOW, body=EMPTY_OPTIONAL, errors=COURSE_WRITE)
add('delete', '/v1/iphone/courses/tag-follows/{tag}', 'iPhone 05 코스·지도', '코스 태그 구독 취소', ('iphone', ('courses:write',)),
    '본문은 비우거나 {}입니다.', '내 태그 구독을 지웁니다. 없어도 성공합니다.', '계정당 60회/분입니다.',
    ok=TAG_FOLLOW, body=EMPTY_OPTIONAL, errors=COURSE_WRITE)
add('put', '/v1/iphone/courses/news/{event_id}/read', 'iPhone 05 코스·지도', '코스 소식 읽음 표시', ('iphone', ('courses:write',)),
    '라이브러리 news[]의 eventId로 호출합니다. 본문은 비우거나 {}입니다.',
    '내 소식 목록에 있는 항목만 읽음으로 기록합니다. 없으면 404입니다.', '반복해도 read=true입니다. 계정당 60회/분입니다.',
    ok=ok(obj({'read': {'const': True, 'description': '읽음.'}}, '읽음 결과.')), body=EMPTY_OPTIONAL, errors=COURSE_WRITE + ('422',))
HIDDEN = ok(obj({'hidden': b('숨김 여부.')}, '숨김 상태.'))
add('put', '/v1/iphone/courses/hidden/{pack_id}/versions/{version}', 'iPhone 05 코스·지도', '공개 코스 숨기기', ('iphone', ('courses:write',)),
    '본문은 비우거나 {}입니다.', '내 라이브러리에서 해당 버전을 숨깁니다. 다른 사람에게는 영향이 없습니다.',
    '계정당 60회/분입니다.', ok=HIDDEN, body=EMPTY_OPTIONAL, errors=COURSE_WRITE + ('422',))
add('delete', '/v1/iphone/courses/hidden/{pack_id}/versions/{version}', 'iPhone 05 코스·지도', '공개 코스 숨김 해제', ('iphone', ('courses:write',)),
    '본문은 비우거나 {}입니다.', '내 숨김만 지웁니다.', '계정당 60회/분입니다.', ok=HIDDEN, body=EMPTY_OPTIONAL,
    errors=COURSE_WRITE + ('422',))
add('post', '/v1/iphone/courses/public/{pack_id}/versions/{version}/reports', 'iPhone 05 코스·지도', '공개 코스 신고', ('iphone', ('courses:write',)),
    'reason(harmful/privacy/rights/other) 하나를 보냅니다.',
    '해당 버전을 검토 대기(quarantined)로 바꾸고 신고 ID를 반환합니다. 같은 사유 재신고는 기존 ID입니다. 판정 완료가 아닙니다.',
    '계정당 60회/분입니다.',
    ok=ok(obj({'reportId': s('신고 ID.'), 'state': s('quarantined.', const='quarantined')}, '신고 접수.'), '신고를 접수했습니다.', '202'),
    body=obj({'reason': s('신고 사유.', enum=['harmful', 'privacy', 'rights', 'other'])}, '정확히 한 필드. 4096바이트 이하.'),
    errors=WRITE + ('422',))

# --------------------------------------------------------------------------- 06 trip planning
TRIP_READ = ('400', '401', '403', '404', '409', '503')
TRIP_WRITE = ('400', '401', '403', '404', '408', '409', '413', '429', '503')
TRIP_NOTE = '본문은 Content-Type: application/json, 4096바이트 이하입니다. 본문이 없는 변경도 {}를 보냅니다.'
add('get', '/v1/iphone/trips', 'iPhone 06 여행 준비', '내 여행과 받은 초대 목록', ('iphone', ('trips:read',)),
    'query 없이 호출합니다.', '참여 중인 여행 요약과 응답 전 초대(준비·진행 중 여행만)를 반환합니다. 차단 관계 방장의 여행은 빠집니다.',
    '조회는 안전합니다.', base=('get', '/v1/social/trips'), errors=READ)
add('post', '/v1/iphone/trips', 'iPhone 06 여행 준비', '여행 만들기', ('iphone', ('trips:manage',)),
    'title·description·memberIds(친구 최대 19명)와 선택적 startDate·endDate·locationConsent를 보냅니다.',
    '여행과 내부 방을 만들고 나를 방장으로 넣습니다. 초대한 친구에게 초대 알림을 예약합니다. 준비·진행 중 여행은 계정당 20개입니다.',
    '새 POST마다 새 여행입니다. 응답을 잃으면 목록을 확인합니다. 계정당 60회/분입니다.',
    base=('post', '/v1/social/trips'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('get', '/v1/iphone/trips/{id}', 'iPhone 06 여행 준비', '여행 상세', ('iphone', ('trips:read',)),
    'query 없이 호출합니다. 웹의 ?section=route는 iPhone에서 400입니다.',
    '수락한 멤버만 읽는 여행 상세(멤버·차·코스·내 권한·공유 설정)를 반환합니다.',
    '알림을 받으면 다시 읽습니다.', base=('get', '/v1/social/trips/{id}'), errors=TRIP_READ)
add('patch', '/v1/iphone/trips/{id}', 'iPhone 06 여행 준비', '여행 제목·설명·날짜 수정', ('iphone', ('trips:manage',)),
    'edit 권한이 필요합니다. title과 description을 함께, 또는 startDate·endDate 두 키만 보냅니다.',
    '여행 정보를 바꾸고 일행에게 변경을 알립니다.', '종료된 여행은 409입니다.',
    base=('patch', '/v1/social/trips/{id}'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('delete', '/v1/iphone/trips/{id}', 'iPhone 06 여행 준비', '종료한 여행 삭제', ('iphone', ('trips:manage',)),
    '방장만 호출합니다. 본문은 {}입니다.', '완료·취소된 여행을 목록에서 지우고 채팅을 삭제합니다.',
    '진행·준비 중이면 409이며 먼저 종료·취소합니다.', base=('delete', '/v1/social/trips/{id}'), body=EMPTY,
    errors=TRIP_WRITE, notes=TRIP_NOTE)
add('post', '/v1/iphone/trips/{id}/members', 'iPhone 06 여행 준비', '친구를 여행에 초대', ('iphone', ('trips:manage',)),
    'invite 권한이 필요합니다. GET /v1/iphone/trips/{id}/friends에서 고른 accountId를 보냅니다.',
    'pending 멤버를 만들고 초대 알림을 예약합니다. 이미 멤버면 200과 현재 상태입니다. 여행은 20명까지입니다.',
    '409 Trip is full이면 인원을 줄입니다.', base=('post', '/v1/social/trips/{id}/members'), body='base', errors=TRIP_WRITE,
    notes=TRIP_NOTE)
add('post', '/v1/iphone/trips/{id}/respond', 'iPhone 06 여행 준비', '여행 초대 수락 또는 거절', ('iphone', ('trips:manage',)),
    '받은 초대에 accept와 선택적 locationConsent를 보냅니다.',
    '수락하면 멤버가 되고 위치 공유 선택을 저장합니다. 거절하면 초대를 지웁니다. 이미 수락했으면 accepted입니다.',
    '초대가 없으면 404입니다.', base=('post', '/v1/social/trips/{id}/respond'),
    body=obj({'accept': b('수락(true) 또는 거절(false).'),
              'locationConsent': dict(b('이번 여행 일행에게 내 위치를 공유할지. 기본 false.'), default=False)},
             '본인 pending 초대에 응답.', required=['accept']),
    errors=TRIP_WRITE, notes=TRIP_NOTE)
add('delete', '/v1/iphone/trips/{id}/members/{accountId}', 'iPhone 06 여행 준비', '여행 나가기 또는 멤버 내보내기', ('iphone', ('trips:manage',)),
    '본인 ID면 나가기, 다른 멤버는 방장만 내보냅니다. 본문은 {}입니다.',
    '멤버와 탑승·장소 선택을 정리하고 일행에게 알립니다.',
    '방장 본인은 409이며 여행을 종료·취소합니다.', base=('delete', '/v1/social/trips/{id}/members/{accountId}'), body=EMPTY,
    errors=TRIP_WRITE, notes=TRIP_NOTE)
add('get', '/v1/iphone/trips/{id}/friends', 'iPhone 06 여행 준비', '여행에 초대할 수 있는 친구 목록', ('iphone', ('trips:read',)),
    'invite 권한이 있는 멤버가 query 없이 호출합니다.',
    '수락한 친구 중 방장과 차단 관계가 아닌 사람과 각자의 여행 참여 상태를 반환합니다.',
    '조회는 안전합니다.', base=('get', '/v1/native/trips/{id}/friends'), errors=TRIP_READ)
add('post', '/v1/iphone/trips/{id}/cars', 'iPhone 06 여행 준비', '내 차를 여행에 추가', ('iphone', ('trips:manage',)),
    '차량을 연결한 멤버가 name·seats(1~8)와 선택적 remotePolicy를 보냅니다.',
    '내가 운전자인 차를 만들고 기존 탑승을 정리합니다. remotePolicy를 켜면 이번 여행 동승자 리모컨 허용을 함께 저장합니다.',
    '이미 운전 중이거나 차량이 없으면 409입니다.', base=('post', '/v1/social/trips/{id}/cars'), body='base',
    errors=TRIP_WRITE, notes=TRIP_NOTE + ' remotePolicy는 iPhone·웹에서만 받으며 차량 앱 경로에서는 403입니다.')
add('patch', '/v1/iphone/trips/{id}/cars/{carId}', 'iPhone 06 여행 준비', '내 차 이름·좌석 수정', ('iphone', ('trips:manage',)),
    '운전자만 name·seats를 보냅니다.', '차 정보를 바꿉니다. 현재 탑승자보다 좌석을 줄이면 409입니다.',
    '409 Seats taken이면 탑승을 먼저 조정합니다.', base=('patch', '/v1/social/trips/{id}/cars/{carId}'), body='base',
    errors=TRIP_WRITE, notes=TRIP_NOTE)
add('delete', '/v1/iphone/trips/{id}/cars/{carId}', 'iPhone 06 여행 준비', '여행에서 차 빼기', ('iphone', ('trips:manage',)),
    '운전자 또는 방장이 {}를 보냅니다.', '차와 탑승·장소·리모컨 허용을 정리합니다.',
    '이미 없는 차는 404입니다.', base=('delete', '/v1/social/trips/{id}/cars/{carId}'), body=EMPTY, errors=TRIP_WRITE,
    notes=TRIP_NOTE)
add('put', '/v1/iphone/trips/{id}/cars/{carId}/ride', 'iPhone 06 여행 준비', '이 차에 탑승 선택', ('iphone', ('trips:manage',)),
    '본문은 {}입니다.', '다른 차 탑승을 정리하고 이 차 동승자가 됩니다. 이미 탑승 중이면 그대로 riding입니다.',
    '좌석이 차면 409입니다.', base=('put', '/v1/social/trips/{id}/cars/{carId}/ride'), body=EMPTY, errors=TRIP_WRITE,
    notes=TRIP_NOTE)
add('delete', '/v1/iphone/trips/{id}/ride', 'iPhone 06 여행 준비', '탑승 해제', ('iphone', ('trips:manage',)),
    '본문은 {}입니다.', '현재 탑승과 그 차의 장소 선택·리모컨 허용을 정리합니다.', '반복해도 left입니다.',
    base=('delete', '/v1/social/trips/{id}/ride'), body=EMPTY, errors=TRIP_WRITE, notes=TRIP_NOTE)
add('post', '/v1/iphone/trips/{id}/courses', 'iPhone 06 여행 준비', '여행에 코스 추가', ('iphone', ('trips:manage',)),
    '수락한 멤버가 현재 공개 코스 packId를 보냅니다.', '코스를 첨부하고 경로 계획을 갱신합니다. 이미 있으면 200입니다. 여행당 10개입니다.',
    '409 Trip course limit이면 코스를 빼고 추가합니다.', base=('post', '/v1/social/trips/{id}/courses'), body='base',
    errors=TRIP_WRITE, notes=TRIP_NOTE)
add('delete', '/v1/iphone/trips/{id}/courses/{packId}', 'iPhone 06 여행 준비', '여행에서 코스 빼기', ('iphone', ('trips:manage',)),
    '추가한 사람 또는 edit 권한자가 {}를 보냅니다.', '코스 첨부를 지우고 경로 계획을 갱신합니다.',
    '없는 코스는 404입니다.', base=('delete', '/v1/social/trips/{id}/courses/{packId}'), body=EMPTY, errors=TRIP_WRITE,
    notes=TRIP_NOTE)
add('put', '/v1/iphone/trips/{id}/courses/priority', 'iPhone 06 여행 준비', '여행 코스 순서 저장', ('iphone', ('trips:manage',)),
    'iPhone에서는 방장만 호출합니다. 현재 packIds 전체 순서와 여행 revision을 보냅니다.',
    '준비 중 여행의 코스 순서를 저장하고 revision을 올립니다.', '409면 상세를 다시 읽습니다.',
    base=('put', '/v1/social/trips/{id}/courses/priority'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('get', '/v1/iphone/trips/{id}/cars/{carId}/places', 'iPhone 06 여행 준비', '차의 픽업·드랍·경유 장소 목록', ('iphone', ('trips:read',)),
    '그 차의 운전자·탑승자가 query 없이 호출합니다.', '차별 장소와 각 장소의 선택 상태를 반환합니다.',
    '조회는 안전합니다.', base=('get', '/v1/social/trips/{id}/cars/{carId}/places'), errors=TRIP_READ)
add('post', '/v1/iphone/trips/{id}/cars/{carId}/places', 'iPhone 06 여행 준비', '차에 장소 추가', ('iphone', ('trips:manage',)),
    '운전자 또는 탑승자가 kind·name·lat·lng를 보냅니다.', '장소를 만들고 경로를 갱신합니다. kind별 10개입니다.',
    '409면 장소를 정리합니다.', base=('post', '/v1/social/trips/{id}/cars/{carId}/places'), body='base', errors=TRIP_WRITE,
    notes=TRIP_NOTE)
add('delete', '/v1/iphone/trips/{id}/cars/{carId}/places/{placeId}', 'iPhone 06 여행 준비', '차 장소 삭제', ('iphone', ('trips:manage',)),
    '추가한 사람 또는 운전자가 {}를 보냅니다.', '장소와 선택을 지우고 경로를 갱신합니다.', '없는 장소는 404입니다.',
    base=('delete', '/v1/social/trips/{id}/cars/{carId}/places/{placeId}'), body=EMPTY, errors=TRIP_WRITE, notes=TRIP_NOTE)
add('put', '/v1/iphone/trips/{id}/cars/{carId}/places/{placeId}/select', 'iPhone 06 여행 준비', '차 장소를 내 픽업·드랍으로 선택', ('iphone', ('trips:manage',)),
    '본문은 {}입니다.', '해당 장소를 내 선택으로 저장하고 경로를 갱신합니다.', '반복해도 같습니다.',
    base=('put', '/v1/social/trips/{id}/cars/{carId}/places/{placeId}/select'), body=EMPTY, errors=TRIP_WRITE, notes=TRIP_NOTE)
add('delete', '/v1/iphone/trips/{id}/cars/{carId}/places/{placeId}/select', 'iPhone 06 여행 준비', '차 장소 선택 해제', ('iphone', ('trips:manage',)),
    '본문은 {}입니다.', '내 선택만 지웁니다.', '반복해도 같습니다.',
    base=('delete', '/v1/social/trips/{id}/cars/{carId}/places/{placeId}/select'), body=EMPTY, errors=TRIP_WRITE, notes=TRIP_NOTE)
PLACE_CHOICE = {'anyOf': [obj({'placeId': s('이 차의 기존 장소 ID.', pattern='^[a-f0-9]{32}$')}, '기존 장소 선택.'),
                          obj({'name': s('장소 이름 1~40자.', maxLength=40), 'lat': {'type': 'number', 'minimum': -90, 'maximum': 90, 'description': '위도.'},
                               'lng': {'type': 'number', 'minimum': -180, 'maximum': 180, 'description': '경도.'}}, '새 장소. 같은 이름·좌표가 있으면 재사용합니다.'),
                          {'type': 'null'}], 'description': '선택 해제는 null.'}
add('put', '/v1/iphone/trips/{id}/cars/{carId}/my-places', 'iPhone 06 여행 준비', '내 픽업·드랍 장소 한 번에 저장', ('iphone', ('trips:manage',)),
    '탑승자가 여행 revision과 pickup·drop(기존 placeId, 새 장소 또는 null), dropAtPickup을 보냅니다. dropAtPickup=true면 drop은 null이고 pickup이 있어야 합니다.',
    '필요하면 새 장소를 만들고 내 선택을 바꾼 뒤 그 차 경로 revision을 1 올립니다. 선택이 그대로면 status=unchanged입니다.',
    '409 TRIP_PLACE_SELECTION_CHANGED면 상세를 다시 읽습니다. 경로 계약 2 여행은 시작 후 409 TRIP_ROUTE_PLAN_LOCKED입니다. kind별 장소 10개 한도입니다.',
    ok=ok(obj({'revision': n('여행 revision.', minimum=1), 'routeRevision': n('이 차 경로 revision.', minimum=0),
               'pickupPlaceId': nullable(s('내 픽업 장소 ID.', pattern='^[a-f0-9]{32}$')), 'dropPlaceId': nullable(s('내 드랍 장소 ID.', pattern='^[a-f0-9]{32}$')),
               'dropAtPickup': b('픽업과 드랍 좌표가 같은지 여부.'), 'status': s('updated 또는 unchanged.', enum=['updated', 'unchanged'])}, '내 장소 선택 결과.')),
    body=obj({'revision': n('직전 상세의 여행 revision.', minimum=1, maximum=2147483647), 'pickup': PLACE_CHOICE, 'drop': PLACE_CHOICE,
              'dropAtPickup': b('픽업한 곳에서 내리는지 여부.')}, '정확히 네 필드.'),
    errors=TRIP_WRITE, notes=TRIP_NOTE)
add('post', '/v1/iphone/trips/{id}/cars/{carId}/ride-invites/{inviteId}/respond', 'iPhone 06 여행 준비', '탑승 초대 수락 또는 거절', ('iphone', ('trips:manage',)),
    '초대 대상 본인이 accept를 보냅니다.', '수락하면 그 차에 탑승합니다.', '이미 처리했거나 없는 초대는 404·409입니다.',
    base=('post', '/v1/social/trips/{id}/cars/{carId}/ride-invites/{inviteId}/respond'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('get', '/v1/iphone/trips/{id}/cars/{carId}/remote-policy', 'iPhone 06 여행 준비', '이 차의 동승자 리모컨 허용 설정 보기', ('iphone', ('trips:read',)),
    '그 차의 운전자 또는 탑승자가 query 없이 호출합니다.',
    'enabled·허용 조작(actions)·차량 deviceId를 반환합니다. 운전석 좌석·창문은 허용 조작과 별개로 항상 원격 제어에서 제외됩니다.',
    '다른 차 사람은 404입니다.', base=('get', '/v1/social/trips/{id}/cars/{carId}/remote-policy'), errors=TRIP_READ)
add('put', '/v1/iphone/trips/{id}/cars/{carId}/remote-policy', 'iPhone 06 여행 준비', '이 차의 동승자 리모컨 허용 저장', ('iphone', ('trips:manage',)),
    '운전자만 enabled·actions와 선택적 deviceId를 보냅니다. deviceId를 생략하면 명령 받기가 켜진 연결 차량이 하나일 때 그 차량을 씁니다.',
    '설정이 바뀌면 이 차의 기존 리모컨 허용과 대기 명령을 철회한 뒤 새 설정을 저장합니다.',
    '409는 차량 없음·리모컨 준비된 차량 없음·차량 선택 필요입니다.',
    base=('put', '/v1/social/trips/{id}/cars/{carId}/remote-policy'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)

# --------------------------------------------------------------------------- 07 trip progress
add('post', '/v1/iphone/trips/{id}/start', 'iPhone 07 여행 진행', '여행 시작', ('iphone', ('trips:manage',)),
    '방장이 현재 revision과 선택적 routeContractVersion(2)·endActiveTrip을 보냅니다.',
    '여행을 active로 바꾸고 일행에게 알립니다. 같은 전환 재요청은 현재 결과입니다.',
    '409면 상세를 다시 읽습니다. 다른 진행 중 여행이 있으면 endActiveTrip으로 명시 종료합니다.',
    base=('post', '/v1/social/trips/{id}/start'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('post', '/v1/iphone/trips/{id}/finish', 'iPhone 07 여행 진행', '여행 종료', ('iphone', ('trips:manage',)),
    '방장이 현재 revision을 보냅니다.', '여행을 completed로 바꾸고 결과 snapshot을 만듭니다.',
    '409면 상세를 다시 읽습니다.', base=('post', '/v1/social/trips/{id}/finish'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('post', '/v1/iphone/trips/{id}/cancel', 'iPhone 07 여행 진행', '여행 취소', ('iphone', ('trips:manage',)),
    '방장이 현재 revision을 보냅니다.', '여행을 cancelled로 바꿉니다.', '409면 상세를 다시 읽습니다.',
    base=('post', '/v1/social/trips/{id}/cancel'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('put', '/v1/iphone/trips/{id}/members/{accountId}/role', 'iPhone 07 여행 진행', '멤버 역할 지정', ('iphone', ('trips:manage',)),
    '방장이 role과 revision을 보냅니다.', '수락 멤버의 역할(예: DJ)을 바꿉니다.', '409면 상세를 다시 읽습니다.',
    base=('put', '/v1/social/trips/{id}/members/{accountId}/role'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('get', '/v1/iphone/trips/{id}/location-sharing', 'iPhone 07 여행 진행', '내 여행 위치 공유 설정 보기', ('iphone', ('trips:read',)),
    'query 없이 호출합니다.', '이번 여행에서 내 위치 공유 선택과 현재 공유 구간 ID를 반환합니다.', '조회는 안전합니다.',
    base=('get', '/v1/social/trips/{id}/location-sharing'), errors=TRIP_READ)
add('patch', '/v1/iphone/trips/{id}/location-sharing', 'iPhone 07 여행 진행', '내 여행 위치 공유 켜기·끄기', ('iphone', ('trips:manage',)),
    'locationConsent를 보냅니다.', '여행 참여를 유지한 채 위치 공유를 바꿉니다. 끄면 일행에게 보이던 내 위치가 사라집니다.',
    '반복해도 같은 결과입니다.', base=('patch', '/v1/social/trips/{id}/location-sharing'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('get', '/v1/iphone/trips/{id}/voice-participation', 'iPhone 07 여행 진행', '내 음성 참여 설정 보기', ('iphone', ('trips:read',)),
    'query 없이 호출합니다. 수정에 쓸 memberJoinedAt·revision을 받습니다.',
    '진행 중 여행의 내 음성 참여 여부를 반환합니다. 기기 마이크 권한과 별개입니다.', '조회는 안전합니다.',
    base=('get', '/v1/social/trips/{id}/voice-participation'), errors=TRIP_READ)
add('patch', '/v1/iphone/trips/{id}/voice-participation', 'iPhone 07 여행 진행', '내 음성 참여 켜기·끄기', ('iphone', ('trips:manage',)),
    '직전 조회의 memberJoinedAt·revision과 participating을 보냅니다.',
    '참여를 바꾸고 음성 연결·메시지 수신 자격을 다시 계산합니다.', '409면 다시 조회합니다.',
    base=('patch', '/v1/social/trips/{id}/voice-participation'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('get', '/v1/iphone/trips/{trip}/locations', 'iPhone 07 여행 진행', '진행 중 여행 일행 위치', ('iphone', ('trips:read',)),
    'query 없이 호출합니다.', '위치 공유를 켠 일행의 최신 위치만 반환합니다. iPhone은 위치를 보내지 않으며 위치 보고는 차량 앱이 합니다.',
    '계정당 60회/분입니다. 진행 중이 아니면 409입니다.', base=('get', '/v1/social/trips/{trip}/locations'), errors=TRIP_READ + ('429',))
add('get', '/v1/iphone/trips/{id}/signals', 'iPhone 07 여행 진행', '손들기 목록', ('iphone', ('trips:read',)),
    'query 없이 호출합니다. iPhone에서는 limit·cursor를 쓸 수 없어 첫 50개만 받습니다.',
    '진행 중·최근 손들기와 투표·결과를 반환합니다.', '알림을 받으면 다시 읽습니다.',
    base=('get', '/v1/social/trips/{id}/signals'), errors=TRIP_READ)
add('post', '/v1/iphone/trips/{id}/signals', 'iPhone 07 여행 진행', '손들기', ('iphone', ('trips:manage',)),
    'kind와 선택적 destination·candidateReceipt(후보 조회 결과)를 보냅니다.',
    '손들기를 만들고 일행 iPhone에 알림을 예약합니다. 진행 중 손들기는 하나뿐입니다.',
    '409 TRIP_SIGNAL_IN_PROGRESS 등은 목록을 다시 읽습니다. 계정당 20회/분입니다.',
    base=('post', '/v1/social/trips/{id}/signals'), body='base', errors=TRIP_WRITE, notes=TRIP_NOTE)
add('post', '/v1/iphone/trips/{id}/signals/candidates', 'iPhone 07 여행 진행', '손들기 주변 장소 후보 조회', ('iphone', ('trips:read', 'maps:read')),
    'kind·location과 선택적 destination·requiredFacilities를 보냅니다. trips:manage가 아닌 trips:read와 maps:read가 필요합니다.',
    '조회 전용 후보를 반환합니다. 진행 방향 앞쪽 후보에는 손들기 생성에 쓸 candidateReceipt가 붙습니다. 손들기를 만들지 않습니다.',
    '429는 Retry-After 60초를 따릅니다.', base=('post', '/v1/social/trips/{id}/signals/candidates'), body='base',
    errors=dict.fromkeys(TRIP_WRITE) | {
        '422': 'CANDIDATES_ROUTE_NOT_FOUND: 카카오 길찾기가 현재 위치에서 목적지까지 경로를 찾지 못했습니다. 목적지를 확인하거나 목적지 없이 진행 방향으로 찾습니다.',
        '429': 'CANDIDATES_RATE_LIMITED: 계정·여행·전체 분당 한도를 넘었습니다. Retry-After: 60을 따릅니다.',
        '502': 'CANDIDATES_PROVIDER_UNAVAILABLE: 카카오 공급자 응답이 없거나 형식이 다릅니다. 후보 없음으로 확정하지 말고 잠시 뒤 다시 찾습니다.',
        '503': 'CANDIDATES_UNAVAILABLE(서버 키 없음), CANDIDATES_BUSY, CANDIDATES_CALL_LIMIT(길찾기 호출 상한) 또는 IPHONE_SERVICE_UNAVAILABLE입니다.',
        '504': 'CANDIDATES_TIMEOUT: 기준 경로를 받기 전에 전체 시간 상한을 넘었습니다. 검색 중 시간 초과는 200 partial=true입니다.'},
    notes=TRIP_NOTE)
add('post', '/v1/iphone/trips/{id}/signals/{signal}/vote', 'iPhone 07 여행 진행', '손들기 응답', ('iphone', ('trips:manage',)),
    'choice(agree/pass)를 보냅니다.',
    '차별 첫 응답을 확정합니다. 같은 차의 추가 응답은 already=true와 최초 응답입니다. 결과가 나면 작성자에게 반응 알림을 예약합니다.',
    '409면 새 손들기로 제안합니다. 계정당 30회/분입니다.', base=('post', '/v1/social/trips/{id}/signals/{signal}/vote'),
    body={'oneOf': [obj({'choice': s('동의 또는 거절.', enum=['agree', 'pass'])}, '내 응답.')], 'description': '손들기 응답.'},
    errors=TRIP_WRITE, notes=TRIP_NOTE)
add('post', '/v1/iphone/trips/{id}/signals/{signal}/finish', 'iPhone 07 여행 진행', '내 손들기 마치기', ('iphone', ('trips:manage',)),
    '작성자가 result(completed/cancelled)를 보냅니다.', '손들기를 마칩니다. 장소가 있는 요청은 합의 규칙으로만 completed가 됩니다.',
    '같은 종료 재시도는 같은 결과입니다.', base=('post', '/v1/social/trips/{id}/signals/{signal}/finish'),
    body=obj({'result': s('마친 결과.', enum=['completed', 'cancelled'])}, '작성자의 종료 선택.'), errors=TRIP_WRITE, notes=TRIP_NOTE)
add('delete', '/v1/iphone/trips/{id}/signals/{signal}/vote', 'iPhone 07 여행 진행', '손들기 응답 철회', ('iphone', ('trips:manage',)),
    '본문은 {}입니다.', '철회할 수 있는 응답만 철회합니다. 확정된 그룹 응답은 바뀌지 않습니다.', '반복해도 같은 결과입니다.',
    base=('delete', '/v1/social/trips/{id}/signals/{signal}/vote'), body=EMPTY, errors=TRIP_WRITE, notes=TRIP_NOTE)
add('get', '/v1/iphone/trips/{id}/driving-versus', 'iPhone 07 여행 진행', '차별 운전 대결 결과', ('iphone', ('trips:read',)),
    'query 없이 호출합니다.', '차량이 보고한 코스별 점수로 만든 차별 대결 상태와 결과를 반환합니다.', '조회는 안전합니다.',
    base=('get', '/v1/native/trips/{id}/driving-versus'), errors=TRIP_READ)
add('get', '/v1/iphone/trips/{id}/driving-score', 'iPhone 07 여행 진행', '여행 전체 운전 점수', ('iphone', ('trips:read',)),
    'query 없이 호출합니다.', '픽업·대기·드랍을 포함한 여행 전체 점수와 차별 결과를 반환합니다.', '조회는 안전합니다.',
    base=('get', '/v1/native/trips/{id}/driving-score'), errors=TRIP_READ)

# --------------------------------------------------------------------------- 08 vehicle remote
add('get', '/v1/iphone/trips/{trip}/vehicle-remotes', 'iPhone 08 차량 리모컨', '내가 조작할 수 있는 여행 차량 리모컨', ('iphone', ('trips:read',)),
    '진행 중 여행의 동승자가 query 없이 호출합니다.',
    '내가 탄 차의 운전자가 허용한 조작과 차량 지원 상태, 최근 요청 5개를 반환합니다. 친구 관계·탑승·차량 명령 받기가 모두 유효할 때만 나타납니다.',
    '알림·화면 복귀 때 다시 읽습니다.', base=('get', '/v1/social/trips/{trip}/vehicle-remotes'),
    errors=TRIP_READ, notes='운전석(ROW_1_LEFT) 좌석·창문은 지원 위치에서 빠집니다.')
add('post', '/v1/iphone/trips/{trip}/vehicle-remotes/{device}/commands', 'iPhone 08 차량 리모컨', '여행 차량에 리모컨 명령 보내기', ('iphone', ('trips:manage',)),
    '동승자가 eventId·grantRevision·capabilityId·capabilityRevision·arguments를 보냅니다.',
    '명령을 queued로 저장해 차량이 가져가게 합니다. 같은 조작·위치의 대기 명령은 superseded가 되고 새 명령은 30초 안에 만료됩니다. 같은 eventId 재전송은 기존 요청입니다.',
    '400은 운전석(ROW_1_LEFT) 좌석·창문 지정이나 범위 밖 값입니다. 422는 차량이 보고한 지원 범위 밖(VEHICLE_CONTROL_UNSUPPORTED/AREA_UNSUPPORTED/VALUE_UNSUPPORTED)입니다. 409면 리모컨 목록을 다시 읽습니다.',
    base=('post', '/v1/social/trips/{trip}/vehicle-remotes/{device}/commands'), body='base',
    errors=dict.fromkeys(('400', '401', '403', '404', '408', '409', '413', '503')) | {
        '422': ('VEHICLE_CONTROL_UNSUPPORTED·VEHICLE_CONTROL_AREA_UNSUPPORTED·VEHICLE_CONTROL_VALUE_UNSUPPORTED: 선택한 차량이 현재 보고한 '
                '지원 범위에 없는 조작·위치·값입니다. 같은 요청을 반복하지 말고 리모컨 목록의 지원 범위를 다시 읽습니다.')},
    notes=('차량이 주행 중이라 실행하지 않으면 요청 reason이 driving-restricted입니다. 시트 열선·통풍과 실내등(light.cabin)은 정차 중에만 실행합니다. '
           'HTTP 성공은 차량 전달 대기일 뿐 실제 실행을 증명하지 않습니다. ' + TRIP_NOTE))

# --------------------------------------------------------------------------- 09 music and voice
PLAYLIST_WRITE = ('400', '401', '403', '404', '409', '413', '429', '503')
add('get', '/v1/iphone/playlists', 'iPhone 09 음악·음성', '내 음악 링크 목록', ('iphone', ('account:read',)),
    'query 없이 호출합니다.', '최근 수정순 최대 100개의 본인 목록을 반환합니다.', '조회는 안전합니다.',
    base=('get', '/v1/playlists'))
add('get', '/v1/iphone/playlists/{playlist_id}', 'iPhone 09 음악·음성', '내 음악 링크 목록 하나', ('iphone', ('account:read',)),
    'query 없이 호출합니다.', '목록 이름·곡·revision을 반환합니다.', '없으면 404입니다.', base=('get', '/v1/playlists/{playlist_id}'))
add('post', '/v1/iphone/playlists', 'iPhone 09 음악·음성', '내 음악 링크 목록 만들기', ('iphone', ('account:write',)),
    'name과 tracks(최대 100곡, HTTPS 링크)를 보냅니다.', '암호화한 새 목록을 만듭니다. 계정당 100개입니다.',
    '새 POST마다 새 목록입니다. 계정당 30회/분입니다.', base=('post', '/v1/playlists'), body='base', errors=PLAYLIST_WRITE,
    notes='본문은 256KiB 이하이며 중복 키는 400입니다.')
add('put', '/v1/iphone/playlists/{playlist_id}', 'iPhone 09 음악·음성', '내 음악 링크 목록 전체 교체', ('iphone', ('account:write',)),
    '현재 revision과 name·tracks 전체를 보냅니다.', '내용을 바꾸고 revision을 올립니다. 이 목록에서 여행에 담은 곡도 갱신됩니다.',
    '409면 다시 읽습니다. 계정당 30회/분입니다.', base=('put', '/v1/playlists/{playlist_id}'), body='base', errors=PLAYLIST_WRITE)
add('delete', '/v1/iphone/playlists/{playlist_id}', 'iPhone 09 음악·음성', '내 음악 링크 목록 삭제', ('iphone', ('account:write',)),
    '현재 revision을 본문 {"revision":N}으로 보냅니다. 웹과 달리 revision이 필요합니다.',
    '목록을 지우고 이 목록에서 여행에 담은 곡을 정리합니다.', '409면 다시 읽습니다. 계정당 30회/분입니다.',
    base=('delete', '/v1/playlists/{playlist_id}'),
    body=obj({'revision': n('직전 조회의 revision.', minimum=1, maximum=2147483647)}, '정확히 한 필드. 4096바이트 이하.'),
    errors=PLAYLIST_WRITE + ('408',))

MUSIC = obj({
    'tripId': ID32,
    'items': arr(obj({'id': ID32, 'title': s('곡 제목.'), 'url': s('HTTPS 링크.', format='uri'), 'addedBy': PERSON,
                      'reviewState': s('private/quarantined/approved/rejected.')}, '여행 음악 항목.'),
                 '차량과 iPhone이 같은 순서로 보는 여행 음악 단일 목록.'),
    'limit': n('여행 음악 최대 개수(200).', minimum=1), 'canAdd': b('지금 내가 추가할 수 있는지 여부.'),
    'canReorder': b('DJ 또는 방장이면 true.'),
    'nowPlaying': arr(obj({'itemId': ID32, 'startedBy': PERSON, 'startedAt': s('차량에서 재생을 시작한 시각.', format='date-time')}, '재생 중인 항목.'),
                      '각 멤버가 차량에서 마지막으로 연 항목. 최신순.'),
    'musicSharing': b('내 함께 듣기(음악 공유) 동의.'),
}, '여행 음악 목록.')
MUSIC_ERR = ('400', '401', '403', '404', '408', '409', '413', '429', '503')
MUSIC_NOTE = '본문은 Content-Type: application/json, 4096바이트 이하이며 query는 허용하지 않습니다.'
add('get', '/v1/iphone/trips/{trip}/music', 'iPhone 09 음악·음성', '여행 음악 목록', ('iphone', ('trips:read',)),
    'query 없이 호출합니다.',
    '여행 음악 단일 목록과 재생 중 항목, 내 함께 듣기 동의를 반환합니다. 함께 듣기가 꺼져 있으면 저장 목록에서 담은 곡만 보입니다.',
    '알림을 받으면 다시 읽습니다.', ok=ok(MUSIC), errors=('400', '401', '403', '404', '409', '503'))
add('patch', '/v1/iphone/trips/{trip}/music/sharing', 'iPhone 09 음악·음성', '함께 듣기 켜기·끄기', ('iphone', ('trips:manage',)),
    'enabled(boolean)를 보냅니다.', '이번 여행의 내 음악 공유 동의만 바꾸고 현재 목록을 반환합니다.', '반복해도 같은 결과입니다.',
    ok=ok(MUSIC), body=obj({'enabled': b('함께 듣기 여부.')}, '정확히 한 필드.'), errors=MUSIC_ERR, notes=MUSIC_NOTE)
add('post', '/v1/iphone/trips/{trip}/music/playlist', 'iPhone 09 음악·음성', '여행 음악에 링크 추가', ('iphone', ('trips:manage',)),
    '함께 듣기를 켠 멤버가 title·url, rightsConfirmed:true, reviewConsent를 보냅니다.',
    '여행 음악 끝에 곡을 추가합니다. reviewConsent=true면 운영 검토도 요청합니다. 여행당 200곡입니다.',
    '새 POST마다 새 항목입니다. 계정당 10곡/분입니다. 403이면 함께 듣기를 먼저 켭니다.',
    ok=ok(MUSIC, '추가한 뒤의 목록입니다.', '201'),
    body=obj({'title': s('곡 제목 1~120자.', maxLength=120), 'url': s('HTTPS 443 링크. 자격증명·공백 금지.', maxLength=2048),
              'rightsConfirmed': {'const': True, 'description': '링크 공유 권리를 사용자가 확인함.'},
              'reviewConsent': b('운영 검토 요청 여부.')}, '정확히 네 필드.'),
    errors=MUSIC_ERR, notes=MUSIC_NOTE)
add('patch', '/v1/iphone/trips/{trip}/music/playlist/{item}/position', 'iPhone 09 음악·음성', '여행 음악 순서 바꾸기', ('iphone', ('trips:manage',)),
    'DJ 또는 방장이 afterId(그 뒤에 둘 항목 ID, 맨 앞이면 null)를 보냅니다.',
    '보이는 항목 순서를 바꾸고 차량·iPhone에 같은 순서를 알립니다.', '409면 목록을 다시 읽습니다.',
    ok=ok(MUSIC), body=obj({'afterId': nullable(s('앞에 올 항목 ID.', pattern='^[a-f0-9]{32}$'))}, '정확히 한 필드.'),
    errors=MUSIC_ERR, notes=MUSIC_NOTE)
add('post', '/v1/iphone/trips/{trip}/music/saved-playlists', 'iPhone 09 음악·음성', '내 음악 링크 목록의 곡을 여행 음악에 담기', ('iphone', ('trips:manage', 'account:read')),
    'playlistId·playlistRevision·trackId와 rightsConfirmed:true, reviewConsent:true를 보냅니다. 세션에 account:read도 있어야 합니다.',
    '선택한 곡을 여행 음악에 한 번만 담고 검토를 요청합니다. 같은 곡 재전송은 기존 항목입니다. 함께 듣기가 꺼져 있어도 담을 수 있습니다.',
    '409면 내 목록을 다시 읽습니다. 계정당 10곡/분입니다.',
    ok=ok(MUSIC), body=obj({'playlistId': ID32, 'playlistRevision': n('내 목록 revision.', minimum=1, maximum=2147483647), 'trackId': ID32,
                            'rightsConfirmed': {'const': True, 'description': '링크 공유 권리 확인.'},
                            'reviewConsent': {'const': True, 'description': '운영 검토 요청.'}}, '정확히 다섯 필드.'),
    errors=MUSIC_ERR, notes=MUSIC_NOTE)

VOICE_NOTE = '진행 중 여행에서만 사용합니다. 본문은 Content-Type: application/json, 1024바이트 이하이며 query는 허용하지 않습니다.'
add('get', '/v1/iphone/trips/{room}/voice/filters', 'iPhone 09 음악·음성', '내 음성 음소거 목록', ('iphone', ('trips:read',)),
    'query 없이 호출합니다.', '이번 여행에서 내가 음소거한 발화자 ID를 반환합니다.', '조회는 안전합니다.',
    base=('get', '/v1/social/trips/{room}/voice/filters'), errors=TRIP_READ)
add('put', '/v1/iphone/trips/{room}/voice/filters/{speaker}', 'iPhone 09 음악·음성', '발화자 음소거·해제', ('iphone', ('trips:manage',)),
    'muted(boolean)를 보냅니다.', '내 수신에서만 그 발화자를 음소거합니다. 열린 음성 연결에도 즉시 반영합니다.', '반복해도 같은 결과입니다.',
    base=('put', '/v1/social/trips/{room}/voice/filters/{speaker}'), body='base', errors=TRIP_WRITE[:-2] + ('503',), notes=VOICE_NOTE)
add('post', '/v1/iphone/trips/{room}/voice/reports', 'iPhone 09 음악·음성', '들은 음성 신고', ('iphone', ('trips:manage',)),
    '실제로 받은 발화의 speakerId·leaseId(실시간 floor 또는 음성 메시지 ID)·reason을 60초 안에 보냅니다.',
    '음성 없이 신고 메타데이터만 저장하고 그 발화자가 말하는 중이면 중지합니다. 판정 완료가 아닙니다.',
    '받지 않은 발화·60초 경과는 404입니다. 계정당 20회/분입니다.', base=('post', '/v1/social/trips/{room}/voice/reports'), body='base',
    errors=TRIP_WRITE, notes=VOICE_NOTE)
CLIP_NOTE = ('음성 메시지는 서버 메모리에만 90초 보관하며 DB·파일에 저장하지 않습니다. 여행당 20개, 전체 64개를 넘으면 오래된 것부터 지웁니다. '
             '수락한 일행 중 나와 차단 관계인 사람이 있으면 목록·보내기·받기 모두 404 VOICE_CLIP_UNAVAILABLE입니다.')
add('get', '/v1/iphone/trips/{trip}/voice-clips', 'iPhone 09 음악·음성', '새 음성 메시지 목록', ('iphone', ('trips:read',)),
    '처음에는 query 없이 호출해 cursor를 받고, 이후 cursor를 보내 새 메시지만 받습니다.',
    '내가 받을 수 있는 새 메시지 메타데이터만 반환합니다. 내가 보낸 것, 음소거한 발화자, 내가 음성에 참여하기 전 메시지는 빠집니다. 일행과 차단 관계가 있으면 목록 대신 404입니다.',
    '서버 재시작으로 cursor가 바뀌면 빈 목록과 새 cursor입니다.', base=('get', '/v1/social/trips/{trip}/voice-clips'),
    params=[query('cursor', '직전 응답의 cursor. 처음에는 생략합니다.', s('부트ID:순번.', pattern='^[a-f0-9]{32}:(0|[1-9][0-9]{0,15})$'))],
    errors=TRIP_READ, notes='음성 참여가 꺼져 있으면 403 VOICE_CLIP_PARTICIPATION_REQUIRED입니다. ' + CLIP_NOTE)
add('post', '/v1/iphone/trips/{trip}/voice-clips', 'iPhone 09 음악·음성', '음성 메시지 보내기', ('iphone', ('trips:manage',)),
    '앱이 만든 clientMessageId(32hex)와 16kHz mono 16bit PCM을 base64로 보냅니다. PCM은 640바이트 배수, 최대 480000바이트(15초)입니다.',
    '지금 음성에 참여 중인 일행에게만 메시지를 공개합니다. 같은 clientMessageId·같은 음성 재전송은 기존 메시지입니다.',
    '409 VOICE_CLIP_MESSAGE_CONFLICT는 같은 ID에 다른 음성입니다. 429 VOICE_CLIP_CAPACITY면 잠시 후 보냅니다. 계정당 60회/분입니다.',
    base=('post', '/v1/social/trips/{trip}/voice-clips'),
    body=obj({'clientMessageId': ID32, 'pcmBase64': s('PCM base64. 최대 640000자.', maxLength=640000)}, '정확히 두 필드. 700000바이트 이하.'),
    errors=TRIP_WRITE, notes='신고 미처리 발화자는 403 VOICE_CLIP_SPEAKER_SUSPENDED입니다. ' + CLIP_NOTE)
add('get', '/v1/iphone/trips/{trip}/voice-clips/{identifier}', 'iPhone 09 음악·음성', '음성 메시지 받기', ('iphone', ('trips:read',)),
    '목록의 id로 query 없이 호출합니다.',
    '재생 직전 송수신 자격을 다시 확인하고 PCM base64를 반환합니다. 받은 기록은 신고 확인에 쓰입니다.',
    '만료·자격 상실은 404 VOICE_CLIP_UNAVAILABLE입니다.', base=('get', '/v1/social/trips/{trip}/voice-clips/{identifier}'),
    errors=TRIP_READ, notes=CLIP_NOTE)

# --------------------------------------------------------------------------- 10 trip records
add('get', '/v1/iphone/trips/{trip}/results', 'iPhone 10 여행 기록', '종료한 여행 결과', ('iphone', ('trips:read',)),
    'query 없이 호출합니다.',
    '완료·취소·나간 여행의 내 기간과 저장한 기록, 완료 여행이면 멤버·차·코스·미션·장소 요약을 반환합니다. 상태 공유를 끈 멤버는 빠집니다.',
    '진행 중 여행은 409입니다.', base=('get', '/v1/social/trips/{trip}/results'), errors=TRIP_READ)
add('get', '/v1/iphone/trips/{trip}/history', 'iPhone 10 여행 기록', '이 여행에서 저장한 내 기록', ('iphone', ('trips:read',)),
    'query 없이 호출합니다.', '이 여행에서 저장한 본인 기록 상세를 반환합니다.',
    '아직 저장하지 않았으면 404 TRIP_HISTORY_NOT_SAVED이며 POST로 저장합니다.',
    ok=ok(ref('History', '본인 기록.')), errors=TRIP_READ)
add('post', '/v1/iphone/trips/{trip}/history', 'iPhone 10 여행 기록', '이 여행을 내 기록으로 저장', ('iphone', ('trips:manage',)),
    '종료한 여행에서 사용자가 title(최대 100자)을 정해 보냅니다.',
    '내 기간의 기록을 만듭니다. 이미 저장했으면 200과 같은 ID입니다. 자동 저장하지 않습니다.',
    '계정당 30회/분입니다.', base=('post', '/v1/social/trips/{trip}/history'),
    body=obj({'title': s('기록 제목 1~100자.', maxLength=100)}, '정확히 한 필드. 2048바이트 이하.'), errors=TRIP_WRITE)
DRAFT_PLACE = obj({'id': s('선택 ID.', pattern='^[a-f0-9]{32}$'), 'courseId': s('원 코스 ID.'), 'version': n('원 코스 버전.', minimum=1),
                   'name': s('장소 이름.'), 'latitude': {'type': 'number', 'description': '위도.'}, 'longitude': {'type': 'number', 'description': '경도.'},
                   'canReuse': b('원작자가 재사용을 허용했거나 내 코스인지 여부.')}, '공유 코스의 장소.')
add('get', '/v1/iphone/trips/{trip}/course-draft-options', 'iPhone 10 여행 기록', '여행 코스 장소로 초안 만들기 선택지', ('iphone', ('trips:read',)),
    '완료한 여행에서 query 없이 호출합니다.',
    '여행 결과의 공개 코스 장소와 재사용 가능 여부, 선택 fingerprint를 반환합니다. 차단 관계 제작자 코스는 빠집니다.',
    '진행 중·결과 없음은 409입니다.',
    ok=ok(obj({'title': s('여행 결과 제목.'), 'selectionFingerprint': s('선택지 지문. 초안 생성에 그대로 보냅니다.'),
               'places': arr(DRAFT_PLACE, '고를 수 있는 장소.')}, '초안 선택지.')), errors=TRIP_READ)
add('post', '/v1/iphone/trips/{trip}/course-drafts', 'iPhone 10 여행 기록', '여행 코스 장소로 내 코스 초안 만들기', ('iphone', ('trips:manage', 'courses:write')),
    'creator·admin 역할이 selectionIds(1~3개, 순서대로)와 selectionFingerprint를 보냅니다. trips:manage와 courses:write가 모두 필요합니다.',
    '고른 장소로 새 편집 초안을 만들고 remixDraftId를 반환합니다. 게시는 POST /v1/iphone/courses로 별도 진행합니다.',
    '409는 선택지가 바뀜·초안 500개 한도, 403은 재사용 미허용입니다. 계정당 20회/분입니다.',
    ok=ok(obj({'pack': ref('DrivePack', '편집할 새 코스 JSON.'), 'tags': arr(s('태그.'), '빈 목록.'), 'hasCover': b('false.'),
               'remixDraftId': s('게시 때 보낼 초안 ID.', pattern='^[a-f0-9]{32}$')}, '새 편집 초안.'), '초안을 만들었습니다.', '201'),
    body=obj({'selectionIds': dict(arr(s('선택 ID.', pattern='^[a-f0-9]{32}$'), '선택 순서.'), minItems=1, maxItems=3, uniqueItems=True),
              'selectionFingerprint': s('선택지 조회의 selectionFingerprint.')}, '정확히 두 필드. 2048바이트 이하.'),
    errors=TRIP_WRITE)

# --------------------------------------------------------------------------- shared-text corrections
# The shared ERRORS text is the Bearer-session baseline. Operations whose handler adds a different
# 401/403/404/413 meaning get that meaning here instead of the baseline.
def _override(keys, code, text):
    for key in keys:
        doc = OPS[key]
        errors = doc['errors'] if isinstance(doc['errors'], dict) else dict.fromkeys(doc['errors'])
        if code not in errors:
            raise RuntimeError('iPhone override for an undocumented code: ' + code + ' ' + repr(key))
        if errors[code] is None:
            errors[code] = text
        doc['errors'] = errors


def _transaction_rechecked(path):
    # team_trips / team_trip_routes transaction(), iphone_trip_music current() and team_data revalidate()
    # compare the account re-authenticated inside the DB transaction with the request's account.
    if path.startswith('/v1/iphone/playlists'):
        return True
    return path.startswith('/v1/iphone/trips') and not any(part in path for part in (
        '/locations', '/voice/', '/voice-clips', '/results', '/history', '/course-draft', '/vehicle-remotes'))


_override([key for key in OPS if _transaction_rechecked(key[1])], '401',
          SESSION_401 + ' 처리 중 다시 확인한 세션 계정이 요청 시작 때와 다르면 AUTHENTICATION_CHANGED입니다. 저장한 토큰을 지우고 로그인부터 다시 합니다.')
_override([('post', '/v1/iphone/courses')], '401',
          SESSION_401 + ' 게시 중 다시 확인한 세션 계정이 다르면 Creator account changed입니다. 저장한 토큰을 지우고 로그인부터 다시 합니다.')
# Handlers that look up no resource by ID answer 404 only at the host boundary.
_override([('get', '/v1/iphone/session'), ('delete', '/v1/iphone/session'), ('put', '/v1/iphone/push/installation'),
           ('delete', '/v1/iphone/push/installation'), ('get', '/v1/iphone/profile'), ('put', '/v1/iphone/profile'),
           ('put', '/v1/iphone/profile/handle'), ('get', '/v1/iphone/vehicles'), ('get', '/v1/iphone/courses'),
           ('get', '/v1/iphone/places/search'), ('post', '/v1/iphone/routes/preview'), ('get', '/v1/iphone/playlists'),
           ('post', '/v1/iphone/playlists'), ('get', '/v1/iphone/friends'), ('get', '/v1/iphone/friends/search'),
           ('get', '/v1/iphone/trips')], '404', 'IPHONE_ROUTE_NOT_FOUND: 전용 iPhone 호스트가 아닌 주소로 왔습니다.')
# Handlers whose only 403 is the session scope check.
_override([('get', '/v1/iphone/session'), ('delete', '/v1/iphone/session'), ('put', '/v1/iphone/push/installation'),
           ('delete', '/v1/iphone/push/installation'), ('get', '/v1/iphone/profile'), ('get', '/v1/iphone/vehicles'),
           ('get', '/v1/iphone/courses'), ('get', '/v1/iphone/courses/{pack_id}/versions/{version}'),
           ('get', '/v1/iphone/places/search'), ('post', '/v1/iphone/routes/preview'), ('get', '/v1/iphone/playlists'),
           ('get', '/v1/iphone/playlists/{playlist_id}'), ('post', '/v1/iphone/playlists'),
           ('put', '/v1/iphone/playlists/{playlist_id}'), ('delete', '/v1/iphone/playlists/{playlist_id}'),
           ('get', '/v1/iphone/friends'), ('get', '/v1/iphone/friends/search')], '403',
          'IPHONE_SCOPE_DENIED: 세션에 이 operation의 scope가 없습니다. scope는 로그인 당시 동의 버전으로 고정되므로 새 scope가 필요하면 다시 로그인합니다.')
# team_data.read_value streams the playlist body itself (no 5-second limit, no IPHONE_ prefix).
_override([('post', '/v1/iphone/playlists'), ('put', '/v1/iphone/playlists/{playlist_id}')], '413',
          'Playlist request too large: 본문이 262144바이트를 넘었습니다. 곡 수(최대 100)나 링크를 사용자가 줄이게 합니다.')

VOICE_SOCKET = {
    'path': '/v1/iphone/trips/{trip}/voice', 'transport': 'WSS',
    'authentication': '전용 iPhone 호스트, Authorization: Bearer <iPhone 세션 토큰>(trips:read). query·subprotocol·Cookie·Origin 헤더는 거절합니다.',
    'transmit': '세션에 trips:manage가 있을 때만 발화(floor-request)할 수 있습니다. 신고 미처리 발화자는 송신이 막힙니다.',
    'conditions': '진행 중(active) 여행의 수락 멤버이며 음성 참여가 켜져 있고 일행과 차단 관계가 없어야 합니다. 음소거한 발화자는 받지 않습니다.',
    'protocol': 'PCM 형식·메시지·제한은 x-wegoh-voice와 같습니다.',
}


# --------------------------------------------------------------------------- apply
def _base_operation(schema, base):
    if base is None:
        return None
    return schema['paths'].get(base[1], {}).get(base[0])


def _plain_body(value):
    content = value.get('requestBody', {}).get('content', {}).get('application/json', {})
    body = copy.deepcopy(content.get('schema'))
    if body and 'oneOf' in body:
        body = next((branch for branch in body['oneOf'] if '$ref' not in branch), None)
    if not body or '$ref' in body:
        raise RuntimeError('iPhone body needs explicit authoring')
    return body


def _parameters(path, extra):
    result = []
    for name in re.findall(r'\{([^}]+)\}', path):
        description, schema = PARAMS[name]
        result.append({'name': name, 'in': 'path', 'required': True, 'description': description, 'schema': copy.deepcopy(schema)})
    return result + copy.deepcopy(extra)


def _security(auth):
    kind = auth[0]
    if kind == 'iphone':
        return [{SECURITY: list(auth[1])}]
    if kind == 'pkce':
        return []
    if kind in ('access', 'access-form'):
        return [{'CloudflareAccess': []}]
    return [{'CloudflareAccess': [], 'TeamSession': [], 'CurrentSessionCSRF': []}]


def build_operation(schema, method, path, doc, iphone_origin, public_origin):
    base = _base_operation(schema, doc['base'])
    if doc['base'] is not None and base is None:
        return None
    if doc['ok'] is not None:
        responses = copy.deepcopy(doc['ok'])
    else:
        responses = {code: copy.deepcopy(value) for code, value in base['responses'].items() if code.startswith('2')}
    if not responses:
        raise RuntimeError('iPhone operation lacks a success response: ' + method + ' ' + path)
    transform = doc.get('transform')
    if transform:
        for value in responses.values():
            media = value.get('content', {}).get('application/json')
            if media:
                media['schema'] = transform(media['schema'])
    errors = doc['errors']
    if not isinstance(errors, dict):
        errors = dict.fromkeys(errors)
    for code, text in sorted(errors.items()):
        responses[code] = {'description': text or ERRORS[code], 'content': {'application/json': {
            # Only the default 422 is FastAPI's path validation; an authored 422 is a handler detail.
            'schema': {'$ref': '#/components/schemas/' + ('ValidationError' if code == '422' and not text else 'ApiError')}}}}
        if code == '429':
            responses[code]['headers'] = {'Retry-After': {'description': '한도 초과 후 기다릴 초. 일부 용량 응답에는 없을 수 있습니다.', 'schema': {'type': 'string'}}}
    browser = doc['auth'][0] in ('access', 'access-form', 'browser')
    sections = ['### 용도\n' + doc['summary'], '### 선행 조건·계정\n' + prerequisite(doc['auth']),
                '### 호출 순서\n' + doc['sequence'], '### 결과·부작용\n' + doc['effects'], '### 재시도·복구\n' + doc['retry']]
    if doc['notes']:
        sections.append(doc['notes'])
    operation = {
        'tags': [doc['tag']], 'summary': doc['summary'], 'description': '\n\n'.join(sections),
        'operationId': operation_id(method, path), 'parameters': _parameters(path, doc['params']),
        'responses': responses, 'security': _security(doc['auth']),
        'servers': [{'url': public_origin if browser else iphone_origin,
                     'description': '공개 웹 호스트.' if browser else '전용 iPhone API 호스트.'}],
        'x-wegoh-surface': 'browser' if browser else 'iphone',
        'x-wegoh-native-access': False,
        'x-wegoh-executable': bool(doc['executable']) if doc['executable'] is not None else False,
        'x-wegoh-documentation': {'authoring': 'explicit-operation-contract',
                                  'review': 'Independent handler/consumer meaning review required; presence is not approval.',
                                  'source': 'iPhone branch of the runtime handler; this document never grants access.'},
    }
    if doc['auth'][0] == 'iphone':
        operation['x-wegoh-iphone-scopes'] = list(doc['auth'][1])
    if not operation['parameters']:
        operation.pop('parameters')
    body = doc['body']
    if body is not None:
        if body == 'base':
            body = _plain_body(base)
        media = doc['body_note'] or 'application/json'
        operation['requestBody'] = {'required': body is not EMPTY_OPTIONAL, 'content': {media: {'schema': copy.deepcopy(body)}}}
    return operation


def mounted_iphone_operations(app):
    """(method, path) of every mounted iPhone HTTP route, including include_in_schema=False ones."""
    from fastapi.routing import APIRoute, iter_route_contexts
    found = set()
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if isinstance(route, APIRoute) and (route.path.startswith('/v1/iphone/') or route.path == '/iphone-login'):
            found.update((method.lower(), route.path) for method in route.methods - {'HEAD', 'OPTIONS'})
    return found


def apply_iphone_documentation(original, auth, app=None):
    """Describe exactly the mounted iPhone routes (all of OPS when app is not given).

    Without a configured iPhone host the routes that stay mounted answer 404; they remain
    described but are marked x-wegoh-configured=false with no server.
    """
    schema = copy.deepcopy(original)
    sessions = getattr(auth, 'iphone_sessions', None)
    origin = getattr(sessions, 'origin', '') or ''
    if app is not None:
        mounted = mounted_iphone_operations(app)
        missing = sorted(mounted - set(OPS))
        if missing:
            raise RuntimeError('Mounted iPhone route lacks authored documentation: ' + repr(missing))
        selected = [key for key in OPS if key in mounted]
    elif origin:
        selected = list(OPS)
    else:
        return schema
    added = 0
    for method, path in selected:
        doc = OPS[(method, path)]
        operation = build_operation(schema, method, path, doc, origin, auth.public_origin)
        if operation is None:
            if app is not None:
                raise RuntimeError('Mounted iPhone route lost its shared contract: ' + repr(doc['base']))
            continue
        if method in schema['paths'].get(path, {}):
            raise RuntimeError('iPhone operation shadows an existing operation: ' + method + ' ' + path)
        operation['x-wegoh-configured'] = bool(origin)
        if not origin:
            operation['servers'] = []
            operation['x-wegoh-executable'] = False
            operation['description'] += '\n\n현재 배포에는 전용 iPhone 호스트가 설정되지 않아 이 경로는 404 IPHONE_ROUTE_NOT_FOUND를 반환합니다.'
        schema['paths'].setdefault(path, {})[method] = operation
        added += 1
    components = schema.setdefault('components', {})
    components.setdefault('securitySchemes', {})[SECURITY] = {
        'type': 'http', 'scheme': 'bearer',
        'description': ('웹에서 승인한 개인 iPhone 세션 토큰(7일). 전용 iPhone 호스트에서만 받으며 Cookie·Origin이 있으면 거절합니다. '
                        'scope 목록은 로그인 당시 동의 버전으로 고정됩니다: ' +
                        '; '.join(scope + ' = ' + text for scope, text in SCOPES.items()) + '. 차량 기기 token·운영 key가 아닙니다.')}
    present = {item['name'] for item in schema.get('tags', [])}
    used = sorted({op['tags'][0] for item in schema['paths'].values() for method, op in item.items()
                   if method in METHODS and op.get('x-wegoh-surface') in ('iphone', 'browser') and op['tags'][0] in TAGS})
    schema.setdefault('tags', []).extend({'name': name, 'description': TAGS[name]} for name in used if name not in present)
    schema['x-wegoh-iphone-voice'] = dict(VOICE_SOCKET, configured=bool(origin),
                                          available=bool(origin and getattr(getattr(auth, 'voice_service', None), 'enabled', False)))
    coverage = schema.get('x-wegoh-documentation-coverage')
    if coverage is not None:
        coverage['iphoneOperations'] = added
        coverage['operations'] = sum(method in METHODS for item in schema['paths'].values() for method in item)
        coverage.setdefault('excluded', [])
        note = '`WSS /v1/iphone/trips/{trip}/voice`: iPhone 여행 음성 PCM WebSocket. 인증·참여·송신 조건은 `x-wegoh-iphone-voice`에 있습니다.'
        if note not in coverage['excluded']:
            coverage['excluded'].append(note)
    return schema
