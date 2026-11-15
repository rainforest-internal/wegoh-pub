"""Opt-in vehicle error reports sent from the error screen."""
from api_doc_device_commands import strict
from api_doc_shared import nullable
from client_reports import MAX_BYTES, MAX_LINE_CHARS, MAX_LINES, MAX_TEXT_BYTES, PATH, PER_GRANT, WINDOW_SECONDS

LINE = {'type': 'string', 'maxLength': MAX_LINE_CHARS,
        'description': '앱이 남긴 WegoH 진단 로그 한 줄(예: `trip.detail: load failed reason=invalid_field trip=1a2b3c4d field=routePlan`). '
        '차량 앱이 먼저 마스킹하고 서버가 같은 규칙으로 다시 마스킹합니다. 계정·기기·grant ID, 토큰, URL, 이메일, 좌표·소수점 4자리 이상 숫자, '
        '12자 이상 16진수, 제목·이름 같은 비ASCII 문자열과 이름·위치 계열 key의 값은 `{masked}`·`{hex}`·`{text}` 등으로 바뀝니다.'}
BODY = strict({
    'reportVersion': {'type': 'integer', 'const': 1, 'description': '보고 형식 1.'},
    'screen': {'type': 'string', 'pattern': '^[a-z][a-z0-9_.]{1,47}$', 'description': '오류가 난 차량 화면의 고정 ID. 예: `trip.detail`, `trip.list`, `account.courses`.'},
    'reason': {'type': 'string', 'pattern': '^[A-Za-z0-9_.-]{1,48}$', 'description': '마지막 실패의 고정 사유 단어. 예: `invalid_field`, `unavailable`. 모르면 `unknown`.'},
    'requestTemplate': nullable({'type': 'string', 'pattern': '^(GET|POST|PUT|PATCH|DELETE|OTHER) /[A-Za-z0-9/{}_?=&.-]{0,159}$',
                                 'description': '실패한 요청의 경로 템플릿. 식별자·질의값은 `{id}`·`{v}`. 모르면 null.'}),
    'appVersion': {'type': 'string', 'pattern': '^[0-9A-Za-z._+-]{1,32}$', 'description': '차량 앱 versionName.'},
    'appBuild': {'type': 'integer', 'minimum': 1, 'maximum': 2147483647, 'description': '차량 앱 versionCode.'},
    'lines': {'type': 'array', 'items': LINE, 'maxItems': MAX_LINES,
              'description': f'앱 프로세스 메모리 링 버퍼의 최근 진단 줄(오래된 것부터). 최대 {MAX_LINES}줄·마스킹 후 {MAX_TEXT_BYTES}bytes. logcat은 읽지 않습니다.'},
}, f'사용자가 오류 화면에서 "오류 보고하기"를 켜고 "전송하기"를 눌렀을 때만 보냅니다. 정확히 이 필드만, 최대 {MAX_BYTES}bytes.')
RESULT = strict({'status': {'const': 'accepted', 'description': '보고 접수.'},
                 'reportId': {'type': 'string', 'pattern': '^[a-f0-9]{16}$', 'description': '무작위 보고 번호. 운영자가 로그를 찾을 때 씁니다. 계정·기기와 연결하지 않습니다.'}},
                '보고는 DB에 저장하지 않고 API 저널의 `wegoh_client_report_v1` 한 줄로만 남습니다.')
OPERATION = dict(
    summary='차량 오류 화면의 진단 보고 전송',
    prerequisites='현재 차량의 mTLS 인증서와 개인 Bearer가 필요합니다. 기능 목적 동의는 요구하지 않지만 현재 grant·설치 slot·credential epoch를 다시 확인합니다.',
    sequence='오류 화면의 "오류 보고하기" 토글은 기본 꺼짐입니다. 사용자가 켜고 "전송하기"를 누르면 한 번 보냅니다. 자동 전송·재전송은 하지 않습니다.',
    effects=('DB·기능 동의·이벤트를 바꾸지 않습니다. 서버가 줄을 다시 마스킹한 뒤 계정·기기·grant ID 없이 무작위 reportId와 함께 '
             '`wegoh_client_report_v1` 저널 한 줄을 씁니다. 수집기가 VictoriaLogs(보관 14일)로 옮깁니다. 저널 한 줄 한도를 넘으면 오래된 줄부터 버리고 truncated=true로 표시합니다.'),
    retry=f'같은 차량 grant당 {WINDOW_SECONDS // 60}분에 {PER_GRANT}건, 서버 전체 120건을 넘으면 429와 Retry-After를 돌려줍니다. 사용자가 다시 누를 때만 재시도합니다.',
    notes='오류 원인 분석용입니다. 제목·좌표·토큰·ID 원문을 보내지 않으며, 수신 결과를 권한 판단에 쓰지 않습니다.',
)


def apply(schema, auth):
    operation = schema.get('paths', {}).get(PATH, {}).get('post')
    if operation is None:
        return schema
    operation.update(summary=OPERATION['summary'], operationId='nativeClientReportPost',
        description=' '.join(OPERATION[key] for key in ('prerequisites', 'sequence', 'effects', 'retry', 'notes')),
        security=[{'NativeMTLS': [], 'DeviceBearer': []}],
        servers=[{'url': auth.native_origin, 'description': 'Native mTLS AND opaque Bearer'}],
        requestBody={'required': True, 'content': {'application/json': {'schema': BODY}}},
        **{'x-wegoh-native-access': True, 'x-wegoh-executable': False})
    operation['responses']['200'] = {'description': '보고 접수.', 'content': {'application/json': {'schema': RESULT}}}
    for code, why in (('400', '형식·필드·패턴 오류'), ('401', '현재 차량 자격이 아님'), ('404', '기능 경로 비활성 또는 기기 사용 불가'),
                      ('408', '본문 수신 5초 초과'), ('413', '본문 또는 마스킹 후 줄 합계 초과'), ('429', '보고 빈도 제한. Retry-After 초 뒤 사용자가 다시 시도'),
                      ('503', '인증 상태 확인 불가')):
        operation['responses'][code] = {'description': why + '. 보고는 기록되지 않습니다.',
            'content': {'application/json': {'schema': {'$ref': '#/components/schemas/NativeFunctionalError'}}}}
    return schema
