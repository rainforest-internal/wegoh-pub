"""Native client failure report: route template, server request/trace id and decode rule only."""
from api_doc_shared import NATIVE, entry, response
from api_doc_models import obj
from client_diagnostics import KINDS, MAX_BYTES, MAX_EVENTS, METHODS, NATIVE_PATH, RATE_PER_MINUTE, RULES

TAG = '진단'
TAG_DESCRIPTION = ('앱이 서버 응답을 받지 못했거나 받은 응답을 거절한 사실을 보고합니다. '
                   '값·식별자 없이 경로 템플릿, 서버 X-Request-Id·trace id와 거절 규칙만 남깁니다.')
EVENT = {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'method', 'route'], 'properties': {
    'kind': {'type': 'string', 'enum': list(KINDS),
             'description': 'network_error=연결 실패, timeout=응답 기한 초과, invalid_response=받은 응답 해석 거절, '
                            'http_error=처리하지 못한 HTTP 오류, cancelled=앱이 요청을 취소.'},
    'method': {'type': 'string', 'enum': list(METHODS), 'description': '실패한 요청의 메서드. WebSocket은 WS.'},
    'route': {'type': 'string', 'maxLength': 200,
              'description': '실패한 요청의 서버 경로 템플릿(예: /v1/native/trips/{id}). 이 서버가 마운트하지 않은 경로(실제 ID를 넣은 경로 포함)의 보고는 건너뛰고 나머지만 기록합니다.'},
    'requestId': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$',
                  'description': '실패한 응답의 X-Request-Id 또는 앱이 보낸 X-Request-Id. 응답이 없으면 생략.'},
    'traceId': {'type': 'string', 'pattern': '^[0-9a-f]{32}$',
                'description': '실패한 응답 traceresponse의 trace id 또는 앱이 보낸 traceparent의 trace id.'},
    'status': {'type': 'integer', 'minimum': 100, 'maximum': 599, 'description': '받은 HTTP 상태. 응답이 없으면 생략.'},
    'decodePath': {'type': 'string', 'pattern': r'^[A-Za-z0-9_$.\[\]-]{1,160}$',
                   'description': 'invalid_response에서 거절한 키 경로(예: routePlan.stops[2].arrival). 값은 넣지 않습니다. '
                                  '16자 이상 hex·7자리 이상 숫자 구간은 서버가 *로 바꿉니다.'},
    'decodeRule': {'type': 'string', 'enum': list(RULES),
                   'description': 'invalid_response에서 필수. missing=키 없음, type=형식 불일치, format=문자열 규칙, '
                                  'range=범위, enum=허용 값 밖, length=길이, unknown=모르는 키, syntax=JSON 구문.'},
    'elapsedMs': {'type': 'integer', 'minimum': 0, 'maximum': 600000, 'description': '요청 시작부터 실패까지 걸린 시간.'}}}
BODY = {'type': 'object', 'additionalProperties': False, 'required': ['events'], 'properties': {
    'events': {'type': 'array', 'minItems': 1, 'maxItems': MAX_EVENTS, 'items': EVENT,
               'description': f'한 번에 최대 {MAX_EVENTS}개. 본문 최대 {MAX_BYTES}bytes.'}},
    'description': '앱 측 실패 보고. 응답 본문·좌표·제목·식별자 값은 받지 않습니다.'}
OPS = {('post', NATIVE_PATH): entry(
    TAG, '차량 앱의 요청 실패·응답 해석 거절 보고',
    NATIVE + ' 현재 개인 access token이 필요하며 필수 scope device:self:manage로 충분합니다.',
    '앱이 요청을 보냈지만 결과를 쓰지 못했을 때(연결 실패·기한 초과·취소·처리 못한 오류·응답 해석 거절) 모아서 보냅니다. '
    '서버 응답의 X-Request-Id와 traceresponse를 같이 넣으면 서버 접근 기록·트레이스와 바로 이어집니다.',
    '서버 로그(wegoh_client_event_v1)와 현재 요청 트레이스의 스팬 이벤트로만 남기며 데이터·권한·동의를 바꾸지 않습니다. '
    '같은 계정 기준 분당 ' + str(RATE_PER_MINUTE) + '회까지 받습니다.',
    '보고 실패는 사용자 동작을 막지 않습니다. 429면 다음 보고 때 합쳐 보내고, 400이면 같은 본문을 반복하지 마세요.',
    {'202': response(obj({'accepted': {'type': 'integer', 'minimum': 0, 'maximum': MAX_EVENTS,
                                       'description': '기록한 보고 수.'},
                          'skipped': {'type': 'integer', 'minimum': 0, 'maximum': MAX_EVENTS,
                                      'description': '마운트되지 않은 경로라 건너뛴 보고 수.'}},
                         '기록한 보고 수와 건너뛴 보고 수.'),
                     '보고를 기록했습니다. 원래 요청의 성공을 뜻하지 않습니다.')},
    ['400', '401', '403', '404', '413', '429', '503'])}
